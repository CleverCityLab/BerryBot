from aiogram.exceptions import TelegramBadRequest
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from utils.logger import get_logger
from utils.secrets import get_admin_ids

from keyboards.client import (
    get_main_inline_keyboard
)

log = get_logger("[Bot.Client]")

client_router = Router()


async def handle_telegram_error(
        e: TelegramBadRequest,
        message: Message = None,
        call: CallbackQuery = None,
        state: FSMContext = None
) -> bool:
    error_text = str(e).lower()

    if "message is not modified" in error_text:
        log.debug("[Bot.Client] Сообщение не изменено (message is not modified)")
        return True

    if (
            "message to delete not found" in error_text
            or "message can't be deleted" in error_text
            or "message to edit not found" in error_text
    ):
        if state:
            await state.clear()
            log.debug("[Bot.Client] FSM состояние очищено из-за ошибки Telegram")

        user = call.from_user if call else message.from_user if message else None
        is_admin = user and user.id in get_admin_ids()

        target = call.message if call else message if message else None
        if target:
            await target.answer(
                text="Не удалось изменить предыдущее сообщение. Выберите действие:",
                reply_markup=get_main_inline_keyboard(is_admin)
            )
            log.info(f"[Bot.Client] Ошибка Telegram обработана для пользователя {user.id if user else 'unknown'}")
        return True

    log.warning(f"[Bot.Client] [UNHANDLED TelegramBadRequest] {e}")
    return False


def register_client(dp):
    dp.include_router(client_router)


@client_router.message(CommandStart())
async def client_start(message: Message, user_manager, account_settings_manager):
    log.info(f"[Bot.Client] Новый старт пользователя {message.from_user.id}")
    user_id = await user_manager.add_user(message.from_user.id, message.from_user.username)
    await account_settings_manager.add_account_setting(user_id)

    is_registered = await account_settings_manager.is_registered(user_id)
    is_admin = message.from_user.id in get_admin_ids()

    await message.answer(
        text="Выбери действие:",
        reply_markup=get_main_inline_keyboard(is_admin)
    )
