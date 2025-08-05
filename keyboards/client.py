from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_inline_keyboard(is_admin: bool):
    buttons = [
        [InlineKeyboardButton(text="Мои заказы", callback_data="my-orders")],
        [InlineKeyboardButton(text="Сделать заказ", callback_data="create-order")],
        [InlineKeyboardButton(text="Изменить мои данные", callback_data="change-profile")],
    ]
    if is_admin:
        buttons = [
            [InlineKeyboardButton(text="Позиции", callback_data="positions")],
            [InlineKeyboardButton(text="Заказы", callback_data="orders")],
            [InlineKeyboardButton(text="Отправить уведомление покупателям", callback_data="send-notification")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
