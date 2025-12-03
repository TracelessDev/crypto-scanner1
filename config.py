import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Бро, где BOT_TOKEN? Добавь его в .env или переменные среды!")

# Список бирж (ключи ccxt ID)
EXCHANGES_CONFIG = {
    'binance': {'enable': True, 'futures': True},
    'bybit': {'enable': True, 'futures': True},
    'mexc': {'enable': True, 'futures': True}
}

# Дефолтные настройки юзера
DEFAULT_SETTINGS = {
    'interval': '5m',
    'threshold_percent': 3.0,
    'rsi_enabled': False,
    'rsi_period': 14,
    'rsi_upper': 70,
    'rsi_lower': 30,
    'filter_24h_change_enabled': False,
    'min_24h_growth': 10.0,
    'signal_type': 'BOTH',
    'exchange_filter': '["binance", "bybit", "mexc"]'
}

DB_NAME = "database.db"
