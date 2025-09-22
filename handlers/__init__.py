# handlers/__init__.py
from aiogram import Dispatcher

from .admin import admin_router
from .client import client_router
from .order_processing import order_router


def register_handlers(dp: Dispatcher):
    """
    Регистрирует все роутеры в главном диспетчере.
    Порядок регистрации ВАЖЕН.
    """
    # Регистрируем роутер с FSM ПЕРВЫМ, чтобы он имел приоритет
    dp.include_router(order_router)

    # Регистрируем остальные роутеры
    dp.include_router(admin_router)
    dp.include_router(client_router)
