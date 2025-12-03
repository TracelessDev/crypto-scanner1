import aiosqlite
import logging
import json

DB_NAME = "data/database.db"
logger = logging.getLogger(__name__)

# Полный фарш настроек
DEFAULT_SETTINGS = {
    'interval': 5,
    'threshold': 3.0,
    'rsi_enabled': False,
    'rsi_timeframe': '5m',     # <--- НОВОЕ: Таймфрейм RSI
    'rsi_period': 14,
    'rsi_pump_limit': 70,      # Если при пампе RSI выше этого -> фильтруем (уже перекуплен)
    'rsi_dump_limit': 30,      # Если при дампе RSI ниже этого -> фильтруем (уже перепродан)
    'filter_24h_enabled': False,
    'min_24h_growth': 5.0,
    'signal_type': 'BOTH',
    'show_imbalance': True,
    'show_funding': True,
    'show_vol24': True,
    'show_listing': False,
    'show_hashtag': True,
    'exchanges': '["binance", "bybit", "mexc"]'
}

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        
        cursor = await db.execute("PRAGMA table_info(users)")
        columns_info = await cursor.fetchall()
        existing_columns = [col[1] for col in columns_info]
        
        for col_name, default_val in DEFAULT_SETTINGS.items():
            if col_name not in existing_columns:
                logger.warning(f"Миграция: добавляю {col_name}")
                col_type = "TEXT"
                if isinstance(default_val, (int, bool)): col_type = "INTEGER"
                elif isinstance(default_val, float): col_type = "REAL"
                
                sql_default = default_val
                if isinstance(default_val, bool): sql_default = 1 if default_val else 0
                elif isinstance(default_val, str): sql_default = f"'{default_val}'"
                
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {sql_default}")
                except Exception as e:
                    logger.error(f"Ошибка миграции {col_name}: {e}")

        await db.commit()
    logger.info("База данных готова.")

async def get_user_settings(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        
        if not row:
            cols = ', '.join(DEFAULT_SETTINGS.keys())
            placeholders = ', '.join(['?'] * len(DEFAULT_SETTINGS))
            vals = [user_id]
            for v in DEFAULT_SETTINGS.values():
                vals.append(int(v) if isinstance(v, bool) else v)
            
            await db.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {placeholders})", vals)
            await db.commit()
            return await get_user_settings(user_id)
            
        return dict(row)

async def update_user_setting(user_id, column, value):
    async with aiosqlite.connect(DB_NAME) as db:
        if isinstance(value, bool): value = 1 if value else 0
        await db.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (value, user_id))
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        return [dict(row) for row in await cursor.fetchall()]