import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from database import get_all_users

logger = logging.getLogger(__name__)

PRICE_BUFFER = {}
BUFFER_RETENTION_MIN = 130 

class MarketEngine:
    def __init__(self, bot):
        self.bot = bot
        self.exchanges = {}
        self.running = True
    
    async def init_exchanges(self):
        options = {
            'enableRateLimit': True, 
            'options': {'defaultType': 'future'},
            'timeout': 30000 
        }
        self.exchanges['binance'] = ccxt.binance(options)
        self.exchanges['bybit'] = ccxt.bybit(options)
        self.exchanges['mexc'] = ccxt.mexc(options)
        logger.info("Коннекторы бирж инициализированы.")

    async def close_exchanges(self):
        for name, exchange in self.exchanges.items():
            await exchange.close()

    async def fetch_tickers_safe(self, exchange_name):
        try:
            exchange = self.exchanges[exchange_name]
            tickers = await exchange.fetch_tickers()
            if not tickers: raise ValueError("Нет данных")
            return exchange_name, tickers
        except Exception:
            return exchange_name, {}

    def clean_buffer(self):
        cutoff = datetime.now() - timedelta(minutes=BUFFER_RETENTION_MIN)
        for exc in PRICE_BUFFER:
            for sym in list(PRICE_BUFFER[exc].keys()):
                PRICE_BUFFER[exc][sym] = {ts: p for ts, p in PRICE_BUFFER[exc][sym].items() if ts > cutoff}
                if not PRICE_BUFFER[exc][sym]: del PRICE_BUFFER[exc][sym]

    async def process_market_data(self):
        logger.info("Сканер запущен. Мониторинг рынка активен.")
        last_debug_print = datetime.now()

        while self.running:
            loop_start = datetime.now()
            
            # Лог состояния раз в минуту (чтобы ты видел, что настройки применились)
            if (datetime.now() - last_debug_print).total_seconds() > 60:
                users_debug = await get_all_users()
                print(f"\n[SYSTEM STATUS] Активных пользователей: {len(users_debug)}")
                for u in users_debug:
                    print(f"ID: {u['user_id']} | Source: {u.get('active_exchange')} | Trigger: {u['threshold']}% ({u['interval']}m)")
                print("-" * 30)
                last_debug_print = datetime.now()

            try:
                results = await asyncio.gather(*[self.fetch_tickers_safe(name) for name in self.exchanges])
            except Exception:
                await asyncio.sleep(5)
                continue

            for exchange_name, tickers in results:
                if not tickers: continue
                if exchange_name not in PRICE_BUFFER: PRICE_BUFFER[exchange_name] = {}

                for symbol, data in tickers.items():
                    if not symbol.endswith(':USDT') and '/USDT' not in symbol: continue
                    if any(x in symbol for x in ['USDC', 'DAI', 'BUSD', '_', 'PERP']): pass
                    
                    price = data.get('last')
                    if not price: continue

                    if symbol not in PRICE_BUFFER[exchange_name]: PRICE_BUFFER[exchange_name][symbol] = {}
                    PRICE_BUFFER[exchange_name][symbol][loop_start] = price

            users = await get_all_users()
            alerts_queue = []

            for ex in PRICE_BUFFER:
                for sym in PRICE_BUFFER[ex]:
                    history = PRICE_BUFFER[ex][sym]
                    curr_price = history[loop_start]
                    
                    intervals_needed = set(u['interval'] for u in users if u.get('active_exchange') == ex)
                    if not intervals_needed: continue

                    for mins in intervals_needed:
                        target_time = loop_start - timedelta(minutes=mins)
                        
                        closest_ts = None
                        min_diff = 999
                        recent_keys = list(history.keys())[-40:] 
                        for ts in recent_keys:
                             diff = abs((ts - target_time).total_seconds())
                             if diff < min_diff:
                                 min_diff = diff
                                 closest_ts = ts
                        
                        if not closest_ts or min_diff > 45: continue

                        old_price = history[closest_ts]
                        pct_change = ((curr_price - old_price) / old_price) * 100
                        
                        for user in users:
                            if user.get('active_exchange') != ex: continue
                            if user['interval'] != mins: continue
                            if abs(pct_change) < user['threshold']: continue

                            is_pump = pct_change > 0
                            if user['signal_type'] == 'PUMP' and not is_pump: continue
                            if user['signal_type'] == 'DUMP' and is_pump: continue

                            alerts_queue.append((user, ex, sym, curr_price, old_price, pct_change, mins))

            for args in alerts_queue:
                await self.process_alert(*args)

            self.clean_buffer()
            await asyncio.sleep(max(1.0, 5.0 - (datetime.now() - loop_start).total_seconds()))

    async def calculate_technicals(self, exchange_name, symbol, price):
        exchange = self.exchanges[exchange_name]
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='5m', limit=20)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
            close = df['close'].to_numpy()
            delta = np.diff(close)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-14:])
            avg_loss = np.mean(loss[-14:])
            rsi = 100 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))

            funding_str = "0%"
            try:
                fund = await exchange.fetch_funding_rate(symbol)
                funding_str = f"{fund['fundingRate'] * 100:.4f}%"
            except: pass
            
            ticker = await exchange.fetch_ticker(symbol)
            
            imbalance_val = 0
            try:
                ob = await exchange.fetch_order_book(symbol, limit=5)
                bids = sum([x[1] for x in ob['bids']])
                asks = sum([x[1] for x in ob['asks']])
                if asks > 0:
                    imbalance_val = ((bids - asks) / asks) * 100
            except: pass

            return {
                'rsi': round(rsi, 1),
                'funding': funding_str,
                'imbalance_pct': imbalance_val,
                'vol_24h': f"${ticker.get('quoteVolume', 0)/1000000:.1f}M",
                'change_24h': ticker.get('percentage', 0)
            }
        except Exception:
            return None

    async def process_alert(self, user, exchange, symbol, price, old_price, change, interval):
        if user.get('active_exchange') != exchange: return 
        if abs(change) < user['threshold']: return

        tech = await self.calculate_technicals(exchange, symbol, price)
        if not tech: return

        if user['filter_24h_enabled']:
            if change > 0 and tech['change_24h'] < user['min_24h_growth']: return

        if user['rsi_enabled']:
            rsi = tech['rsi']
            if change > 0 and rsi > user['rsi_pump_limit']: return
            if change < 0 and rsi < user['rsi_dump_limit']: return

        # === НОВЫЙ ДИЗАЙН СИГНАЛА ===
        is_pump = change > 0
        emoji_side = "⚡️" if is_pump else "🔻"
        color_side = "🟢" if is_pump else "🔴"
        action_text = "РОСТ ЦЕНЫ" if is_pump else "ПАДЕНИЕ ЦЕНЫ"
        
        pair_clean = symbol.split('/')[0].replace(':USDT','')
        pair_display = f"#{pair_clean}" if user['show_hashtag'] else pair_clean
        
        # Шапка
        msg = [
            f"{emoji_side} <b>{pair_display}</b> | {exchange.upper()} Futures",
            f"{color_side} <b>{action_text}: {change:+.2f}%</b> (за {interval} мин)",
            f"💵 Цена: <code>{old_price}</code> ➔ <code>{price}</code>",
            "───────────────────"
        ]
        
        # Технические данные (компактно)
        tech_lines = []
        if user['rsi_enabled']:
            rsi_val = tech['rsi']
            rsi_status = "Перекуплен" if rsi_val > 70 else "Перепродан" if rsi_val < 30 else "Нейтрально"
            tech_lines.append(f"📊 RSI (5m): <b>{rsi_val}</b> ({rsi_status})")
        
        if user['show_vol24']:
            # Красивый вывод объема с динамикой
            tech_lines.append(f"💰 Объем 24ч: <b>{tech['vol_24h']}</b> ({tech['change_24h']:+.1f}%)")
            
        if user['show_imbalance']:
            imb = tech['imbalance_pct']
            imb_txt = f"Покупатели +{imb:.1f}%" if imb > 0 else f"Продавцы +{abs(imb):.1f}%"
            side_dot = "🟢" if imb > 0 else "🔴"
            tech_lines.append(f"⚖️ Стакан: {side_dot} {imb_txt}")
            
        if user['show_funding']:
            tech_lines.append(f"🧩 Фандинг: {tech['funding']}")
        
        if tech_lines:
            msg.extend(tech_lines)
            msg.append("───────────────────")
        
        # Подвал
        msg.append(f"📡 ID: {int(datetime.now().timestamp())}") # Уникальность сообщения
        
        try:
            await self.bot.send_message(user['user_id'], "\n".join(msg), parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")

async def run_screener(bot):
    engine = MarketEngine(bot)
    await engine.init_exchanges()
    try:
        await engine.process_market_data()
    except asyncio.CancelledError:
        pass
    finally:
        await engine.close_exchanges()