from aiogram import BaseMiddleware, Bot

from database.async_db import AsyncDatabase


class ManagerMiddleware(BaseMiddleware):
    def __init__(
            self,
            db: AsyncDatabase,
            bot: Bot,
    ):
        super().__init__()
        self.db = db
        self.bot = bot

    async def __call__(self, handler, event, data):
        data["db"] = self.db
        data["bot"] = self.bot

        return await handler(event, data)
