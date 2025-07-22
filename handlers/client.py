from aiogram import Router
from utils.logger import get_logger

log = get_logger("[Bot.Admin]")

client_router = Router()


def register_client(dp):
    dp.include_router(client_router)
