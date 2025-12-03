import aiosqlite
import logging

DB_NAME = "database.db"
logger = logging.getLogger(__name__)

# Полная конфигурация
DEFAULT_SETTINGS = {
    'interval': 5,
    'threshold': 3.0,
    'rsi_enabled': False,
    'rsi_period': 14,
    'rsi_pump_limit': 30,
    'rsi_dump_limit': 70,
    'filter_24h_enabled': False,
    'min_24h_growth': 5.0,
    'signal_type': 'BOTH',
    'show_imbalance': True,
    'show_funding': True,
    'show_vol24': True,
    'show_listing': False,
    'show_hashtag': True,
    'active_exchange': 'binance'
}

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Создаем таблицу, если нет
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        # 2. АВТО-МИГРАЦИЯ: Проверяем и добавляем недостающие колонки
        cursor = await db.execute("PRAGMA table_info(users)")
        columns_info = await cursor.fetchall()
        existing_columns = [col[1] for col in columns_info]
        
        for col_name, default_val in DEFAULT_SETTINGS.items():
            if col_name not in existing_columns:
                logger.warning(f"⚠️ Миграция: Добавляю колонку '{col_name}'...")
                
                # Определение типа SQL
                col_type = "TEXT"
                if isinstance(default_val, bool) or isinstance(default_val, int):
                    col_type = "INTEGER"
                elif isinstance(default_val, float):
                    col_type = "REAL"
                
                # Конвертация булевых значений для SQL
                sql_default = default_val
                if isinstance(default_val, bool):
                    sql_default = 1 if default_val else 0
                elif isinstance(default_val, str):
                    sql_default = f"'{default_val}'"
                
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type} DEFAULT {sql_default}")
                except Exception as e:
                    logger.error(f"Ошибка миграции {col_name}: {e}")

        await db.commit()
    logger.info("✅ База данных проверена и обновлена.")

async def get_user_settings(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        
        if not row:
            # Создание нового пользователя
            cols = ', '.join(DEFAULT_SETTINGS.keys())
            placeholders = ', '.join(['?'] * len(DEFAULT_SETTINGS))
            
            # Подготовка значений (bool -> int)
            vals = [user_id]
            for v in DEFAULT_SETTINGS.values():
                vals.append(int(v) if isinstance(v, bool) else v)
            
            await db.execute(f"INSERT INTO users (user_id, {cols}) VALUES (?, {placeholders})", vals)
            await db.commit()
            return await get_user_settings(user_id)
            
        return dict(row)

async def update_user_setting(user_id, column, value):
    async with aiosqlite.connect(DB_NAME) as db:
        # Конвертация bool -> int для SQLite
        if isinstance(value, bool):
            value = 1 if value else 0
            
        query = f"UPDATE users SET {column} = ? WHERE user_id = ?"
        await db.execute(query, (value, user_id))
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
