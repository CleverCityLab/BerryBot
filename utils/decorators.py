from datetime import datetime
from functools import wraps
import logging

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from utils.secrets import get_admin_ids
from keyboards.client import get_main_inline_keyboard

log = logging.getLogger("[Bot.Decorator]")


async def handle_telegram_error(
        e: TelegramBadRequest,
        message: types.Message = None,
        call: types.CallbackQuery = None,
        state: FSMContext = None
) -> bool:
    error_text = str(e).lower()

    if "message is not modified" in error_text:
        log.debug("[Bot.Decorator] Сообщение не изменено (message is not modified)")
        return True

    if (
            "message to delete not found" in error_text
            or "message can't be deleted" in error_text
            or "message to edit not found" in error_text
    ):
        if state:
            await state.clear()
            log.debug("[Bot.Decorator] FSM состояние очищено из-за ошибки Telegram")

        user = call.from_user if call else message.from_user if message else None
        is_admin = user and user.id in get_admin_ids()

        target = call.message if call else message if message else None
        if target:
            await target.answer(
                text="Не удалось изменить предыдущее сообщение. Выберите действие:",
                reply_markup=get_main_inline_keyboard(is_admin)
            )
            log.info(f"[Bot.Decorator] Ошибка Telegram обработана для пользователя {user.id if user else 'unknown'}")
        return True

    log.warning(f"[Bot.Decorator] [UNHANDLED TelegramBadRequest] {e}")
    return False


def _get_ctx(args, kwargs):
    message = next((a for a in args if isinstance(a, types.Message)), None)
    call = next((a for a in args if isinstance(a, types.CallbackQuery)), None)
    state = next((a for a in args if isinstance(a, FSMContext)), None) \
            or next((v for v in kwargs.values() if isinstance(v, FSMContext)), None)
    return message, call, state


async def _clear_and_show(target, state, text, is_admin=False):
    try:
        if isinstance(target, types.CallbackQuery):
            await target.bot.delete_message(
                chat_id=target.message.chat.id,
                message_id=target.message.message_id
            )
        elif isinstance(target, types.Message):
            data = await state.get_data() if state else {}
            msg_id = data.get("form_msg_id")
            if msg_id:
                await target.bot.edit_message_reply_markup(
                    chat_id=target.chat.id,
                    message_id=msg_id,
                    reply_markup=None
                )
    except TelegramBadRequest as e:
        log.error("[Bot.Decorator] Ошибка при удалении/редактировании сообщения: %s", e)
        await handle_telegram_error(e, message=target if isinstance(target, types.Message) else None,
                                    call=target if isinstance(target, types.CallbackQuery) else None, state=state)

    send = (target.message.answer if isinstance(target, types.CallbackQuery) else target.answer)
    await send(text)
    await send(
        "Выберите действие:",
        reply_markup=get_main_inline_keyboard(is_admin)
    )
    log.info("[Bot.Decorator] Отправлено меню выбора действия пользователю.")

    if state:
        await state.clear()
        log.debug("[Bot.Decorator] FSM состояние очищено после показа сообщения.")


def admin_only(handler):
    @wraps(handler)
    async def wrapper(*args, **kwargs):
        message, call, state = _get_ctx(args, kwargs)
        user_id = (message.from_user.id if message else call.from_user.id if call else None)

        if user_id not in get_admin_ids():
            log.warning(
                f"[Bot.Decorator] Пользователь {user_id} пытался зайти в {handler.__name__} без прав администратора")
            await _clear_and_show(
                call or message, state, "Извините, у вас недостаточно прав для этого действия.", is_admin=False)
            return
        return await handler(*args, **kwargs)

    return wrapper
