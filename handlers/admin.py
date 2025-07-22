from aiogram import Router
from utils.logger import get_logger

log = get_logger("[Bot.Admin]")

admin_router = Router()


def register_admin(dp):
    dp.include_router(admin_router)
