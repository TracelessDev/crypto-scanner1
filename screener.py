import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
import logging
import json
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
        logger.info("Core Systems Online.")

    async def close_exchanges(self):
        for name, exchange in self.exchanges.items():
            await exchange.close()

    async def fetch_tickers_safe(self, exchange_name):
        try:
            exchange = self.exchanges[exchange_name]
            tickers = await exchange.fetch_tickers()
            if not tickers: raise ValueError("No Data")
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
        logger.info("Market Monitor Active.")
        
        while self.running:
            loop_start = datetime.now()
            
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
                    
                    # Оптимизация: собираем нужные интервалы
                    intervals_needed = set()
                    for u in users:
                        try: allowed = json.loads(u['exchanges'])
                        except: allowed = []
                        if ex in allowed: intervals_needed.add(u['interval'])

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
                        
                        if not closest_ts or min_diff > 60: continue

                        old_price = history[closest_ts]
                        pct_change = ((curr_price - old_price) / old_price) * 100
                        
                        for user in users:
                            # 1. Биржа
                            try: allowed = json.loads(user['exchanges'])
                            except: allowed = []
                            if ex not in allowed: continue

                            # 2. Параметры
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

    async def calculate_technicals(self, exchange_name, symbol, price, user_settings):
        exchange = self.exchanges[exchange_name]
        try:
            # RSI с учетом таймфрейма юзера!
            rsi_tf = user_settings.get('rsi_timeframe', '5m')
            rsi_period = user_settings.get('rsi_period', 14)
            
            # Берем чуть больше свечей, чтобы хватило на расчет
            limit = rsi_period + 10
            
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=rsi_tf, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
            close = df['close'].to_numpy()
            
            delta = np.diff(close)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            
            # Simple RSI calc
            avg_gain = np.mean(gain[-rsi_period:])
            avg_loss = np.mean(loss[-rsi_period:])
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            # Funding
            funding_str = "0.00%"
            try:
                fund = await exchange.fetch_funding_rate(symbol)
                funding_str = f"{fund['fundingRate'] * 100:.4f}%"
            except: pass
            
            # 24h & Vol
            ticker = await exchange.fetch_ticker(symbol)
            
            # Imbalance
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
        # Двойной чек биржи
        try:
            if exchange not in json.loads(user['exchanges']): return
        except: return
        
        if abs(change) < user['threshold']: return

        # Передаем настройки юзера в калькулятор, чтобы взять правильный RSI TF
        tech = await self.calculate_technicals(exchange, symbol, price, user)
        if not tech: return

        # Фильтр Тренда 24ч
        if user['filter_24h_enabled']:
            if change > 0 and tech['change_24h'] < user['min_24h_growth']: return

        # --- ГИБКИЙ RSI ФИЛЬТР ---
        if user['rsi_enabled']:
            rsi = tech['rsi']
            
            # Логика:
            # При ПАМПЕ (+): Если RSI уже перегрет (выше pump_limit), сигнал не нужен (поздно заходить).
            if change > 0 and rsi > user['rsi_pump_limit']: return
            
            # При ДАМПЕ (-): Если RSI уже на дне (ниже dump_limit), сигнал не нужен (шортить поздно).
            if change < 0 and rsi < user['rsi_dump_limit']: return

        # Сборка сообщения
        is_pump = change > 0
        side_color = "🟢" if is_pump else "🔴"
        action = "Рост цены" if is_pump else "Снижение цены"
        
        pair_clean = symbol.split('/')[0].replace(':USDT','')
        pair_fmt = f"#{pair_clean}" if user['show_hashtag'] else pair_clean
        
        msg = [
            f"{side_color} <b>{pair_fmt}</b> | {exchange.capitalize()}",
            f"{action}: <b>{change:+.2f}%</b> ({interval} мин)",
            f"Цена: {old_price} ➔ {price}",
            "────────────────"
        ]
        
        if user['rsi_enabled']:
            # Показываем TF, на котором считали
            tf_icon = user.get('rsi_timeframe', '5m')
            msg.append(f"RSI ({tf_icon}): <b>{tech['rsi']}</b>")
        
        if user['show_vol24']:
            msg.append(f"Vol 24h: {tech['vol_24h']} (Изм. {tech['change_24h']:+.1f}%)")
            
        if user['show_imbalance']:
            arrow = "↑" if tech['imbalance_pct'] > 0 else "↓"
            msg.append(f"Стакан: {arrow} {abs(tech['imbalance_pct']):.1f}% (Bid/Ask)")
            
        if user['show_funding']:
            msg.append(f"Funding: {tech['funding']}")
            
        msg.append("────────────────")
        
        try:
            await self.bot.send_message(user['user_id'], "\n".join(msg), parse_mode="HTML")
        except Exception as e:
            logger.error(f"Delivery failed: {e}")

async def run_screener(bot):
    engine = MarketEngine(bot)
    await engine.init_exchanges()
    try:
        await engine.process_market_data()
    except asyncio.CancelledError:
        pass
    finally:
        await engine.close_exchanges()