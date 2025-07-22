import sys
import signal
import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher

from database.async_db import AsyncDatabase
from utils.logger import get_logger, setup_logging
from utils.config import (
    BOT_TOKEN, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    DB_MIN_POOL_SIZE, DB_MAX_POOL_SIZE
)

from middleware.manager_middleware import ManagerMiddleware
from handlers import register_handlers

setup_logging(level=logging.DEBUG, log_to_file=True)
log = get_logger("[Bot]")


async def shutdown(bot: Bot, dp: Dispatcher):
    log.info("[Bot] Начало завершения работы бота и диспетчера")

    for mw in dp.update.middleware._middlewares:
        if isinstance(mw, ManagerMiddleware) and mw.db:
            with suppress(Exception):
                await mw.db.close()
                log.debug("[Bot] Подключение к базе данных закрыто [✓]")

    with suppress(Exception):
        await dp.storage.close()
        log.debug("[Bot] Диспетчер storage закрыт [✓]")

    with suppress(Exception):
        await bot.session.close()
        log.debug("[Bot] Сессия бота закрыта [✓]")

    log.info("[Bot] Завершение работы бота и диспетчера завершено [✓]")
    log.info("-" * 80)


async def main():
    log.info("[Bot] Запуск основного процесса")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    db = AsyncDatabase(
        db_name=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        min_size=DB_MIN_POOL_SIZE,
        max_size=DB_MAX_POOL_SIZE,
    )
    await db.connect()
    log.info("[Bot] Подключение к базе данных установлено [✓]")

    dp.update.middleware(
        ManagerMiddleware(
            db=db,
            bot=bot,
        )
    )
    log.info("[Bot] Middleware настроен [✓]")

    register_handlers(dp)
    log.info("[Bot] Обработчики зарегистрированы [✓]")

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: loop.create_task(shutdown(bot, dp)))

        log.info("[Bot] Бот запущен. Ожидание завершения через Ctrl+C")
        try:
            await dp.start_polling(bot)
        finally:
            await shutdown(bot, dp)
    else:
        try:
            log.info("[Bot] Бот запущен. Ожидание завершения через Ctrl+C")
            await dp.start_polling(bot)
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            log.warning("[Bot] Получен сигнал завершения работы")
        finally:
            await shutdown(bot, dp)


if __name__ == "__main__":
    log.info("-" * 80)
    log.info("[Bot] Запуск приложения")
    asyncio.run(main())
