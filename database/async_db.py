from typing import Any, List, Optional

import asyncpg
from asyncpg.pool import Pool

from utils.logger import get_logger

log = get_logger(__name__)


class AsyncDatabase:
    """
    Базовый интерфейсный класс для работы с PostgreSQL через asyncpg.
    Предоставляет методы для выполнения SQL-запросов.
    """

    def __init__(
            self,
            db_name: str,
            user: str,
            password: str,
            host: str = "localhost",
            port: int = 5432,
            min_size: int = 10,
            max_size: int = 100
    ):
        self.db_name = db_name
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Optional[Pool] = None

    async def connect(self) -> None:
        """
        Устанавливает пул соединений к базе данных.
        """
        try:
            self.pool = await asyncpg.create_pool(
                database=self.db_name,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                min_size=self.min_size,
                max_size=self.max_size
            )
            log.debug("[DB] Подключение к базе данных успешно установлено")
        except Exception as e:
            log.exception(f"[DB] Ошибка при подключении к базе данных: {e}")

    async def close(self) -> None:
        """
        Закрывает пул соединений.
        """
        if self.pool:
            await self.pool.close()
            log.debug("[DB] Соединение с базой данных закрыто.")

    async def execute(self, query: str, *args: Any) -> str:
        """
        Выполняет запрос без возврата данных (INSERT, UPDATE, DELETE).
        """
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        """
        Выполняет SELECT-запрос и возвращает все строки.
        """
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """
        Выполняет SELECT-запрос и возвращает одну строку.
        """
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any, column: int = 0) -> Any:
        """
        Выполняет SELECT-запрос и возвращает одно значение.
        """
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchval(query, *args, column=column)
