import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database import init_db
from bot_handlers import router
from screener import run_screener

# Чистим логи, чтобы не спамило лишним
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    # 1. Запуск базы данных
    await init_db()
    
    # 2. Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    # 3. Запуск скринера (фоном)
    # Создаем задачу и сохраняем ссылку на нее
    screener_task = asyncio.create_task(run_screener(bot))
    
    try:
        logger.info("🚀 БОТ ЗАПУЩЕН (Режим: Скрипт)")
        
        # Удаляем вебхуки, если они вдруг висели, чтобы поллинг пошел сразу
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем поллинг (это бесконечный цикл, который держит бота живым)
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        logger.info("🛑 Остановка...")
        screener_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен вручную.")