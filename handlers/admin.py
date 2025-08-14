import asyncio

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery

from keyboards.admin import (admin_positions_list,
                             admin_edit_back,
                             admin_pos_detail,
                             admin_confirm_delete,
                             get_admin_orders_keyboard,
                             get_admin_orders_list_kb,
                             admin_order_detail_kb,
                             admin_cancel_confirm_kb, notify_cancel_kb, notify_confirm_kb
                             )
from keyboards.client import get_main_inline_keyboard

from utils.decorators import admin_only
from utils.logger import get_logger
from utils.secrets import get_admin_ids

log = get_logger("[Bot.Admin]")

admin_router = Router()


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


class PosEdit(StatesGroup):
    add_title = State()
    add_price = State()
    add_qty = State()
    edit_title = State()
    edit_price = State()
    edit_qty = State()


class AdminNotify(StatesGroup):
    waiting_message = State()
    confirm = State()


def register_admin(dp):
    dp.include_router(admin_router)


@admin_router.callback_query(F.data == "back-admin-main")
@admin_only
async def back_admin_main(call: CallbackQuery):
    try:
        await call.message.edit_text("Выберите действие:", reply_markup=get_main_inline_keyboard(is_admin=True))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.callback_query(F.data == "positions")
@admin_only
async def adm_positions(call: CallbackQuery, product_position_manager):
    items = await product_position_manager.list_all_order_positions()
    try:
        await call.message.edit_text("Текущие позиции:", reply_markup=admin_positions_list(items))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.callback_query(F.data == "adm-pos:back-list")
@admin_only
async def adm_pos_back_list(call: CallbackQuery, product_position_manager):
    items = await product_position_manager.list_all_order_positions()
    try:
        await call.message.edit_text("Текущие позиции:", reply_markup=admin_positions_list(items))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.callback_query(F.data == "adm-pos:add")
@admin_only
async def adm_pos_add_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(PosEdit.add_title)
    try:
        await call.message.edit_text("Введите *название позиции*:", parse_mode="Markdown",
                                     reply_markup=admin_edit_back())
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.message(PosEdit.add_title)
@admin_only
async def adm_pos_add_title(msg: Message, state: FSMContext):
    title = msg.text.strip()
    if not title or len(title) > 50:
        await msg.answer("Название пустое или слишком длинное (≤ 50).")
        return
    await state.update_data(title=title)
    await state.set_state(PosEdit.add_price)
    await msg.answer("Введите *цену* (целое число ≥ 0):", parse_mode="Markdown")


@admin_router.message(PosEdit.add_price)
@admin_only
async def adm_pos_add_price(msg: Message, state: FSMContext):
    try:
        price = int(msg.text)
        assert price >= 0
    except Exception:
        await msg.answer("Цена должна быть целым числом ≥ 0.")
        return
    await state.update_data(price=price)
    await state.set_state(PosEdit.add_qty)
    await msg.answer("Введите *количество* (целое число ≥ 0):", parse_mode="Markdown")


@admin_router.message(PosEdit.add_qty)
@admin_only
async def adm_pos_add_qty(msg: Message, state: FSMContext, product_position_manager):
    try:
        qty = int(msg.text)
        assert qty >= 0
    except Exception:
        await msg.answer("Количество должно быть целым числом ≥ 0.")
        return
    data = await state.get_data()
    pid = await product_position_manager.create_position(data["title"], data["price"], qty)
    await state.clear()
    pos = await product_position_manager.get_order_position_by_id(pid)
    text = (f"*Наименование:* {pos['title']}\n"
            f"*Цена:* `{pos['price']}` руб.\n"
            f"*Оставшееся количество:* `{pos['quantity']}` шт")
    await msg.answer("Позиция *успешно добавлена* ✅", parse_mode="Markdown")
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


@admin_router.message(PosEdit.edit_title)
@admin_only
async def adm_pos_edit_title_set(msg: Message, state: FSMContext, product_position_manager):
    name = " ".join(msg.text.split()).strip()
    if not name or len(name) > 50:
        await msg.answer("Название пустое или слишком длинное (≤ 50).")
        return
    pid = (await state.get_data())["pid"]
    await product_position_manager.update_title(pid, name)
    await state.clear()
    pos = await product_position_manager.get_order_position_by_id(pid)
    text = (f"*Наименование:* {pos['title']}\n"
            f"*Цена:* `{pos['price']}` руб.\n"
            f"*Оставшееся количество:* `{pos['quantity']}` шт")
    await msg.answer("Название *успешно изменено* ✅", parse_mode="Markdown")
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


@admin_router.callback_query(F.data.startswith("adm-pos:edit-price:"))
@admin_only
async def adm_pos_edit_price_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[2])
    await state.update_data(pid=pid)
    await state.set_state(PosEdit.edit_price)
    try:
        await call.message.edit_text("Введите *новую цену* (целое число ≥ 0):", parse_mode="Markdown",
                                     reply_markup=admin_edit_back(pid))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.message(PosEdit.edit_price)
@admin_only
async def adm_pos_edit_price_set(msg: Message, state: FSMContext, product_position_manager):
    try:
        price = int(msg.text)
        assert price >= 0
    except Exception:
        await msg.answer("Цена должна быть целым числом ≥ 0.")
        return
    pid = (await state.get_data())["pid"]
    await product_position_manager.update_price(pid, price)
    await state.clear()
    pos = await product_position_manager.get_order_position_by_id(pid)
    text = (f"*Наименование:* {pos['title']}\n"
            f"*Цена:* `{pos['price']}` руб.\n"
            f"*Оставшееся количество:* `{pos['quantity']}` шт")
    await msg.answer("Цена *успешно изменена* ✅", parse_mode="Markdown")
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


@admin_router.callback_query(F.data.startswith("adm-pos:edit-qty:"))
@admin_only
async def adm_pos_edit_qty_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[2])
    await state.update_data(pid=pid)
    await state.set_state(PosEdit.edit_qty)
    try:
        await call.message.edit_text("Введите *новое количество* (целое число ≥ 0):", parse_mode="Markdown",
                                     reply_markup=admin_edit_back(pid))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.message(PosEdit.edit_qty)
@admin_only
async def adm_pos_edit_qty_set(msg: Message, state: FSMContext, product_position_manager):
    try:
        qty = int(msg.text)
        assert qty >= 0
    except Exception:
        await msg.answer("Количество должно быть целым числом ≥ 0.")
        return
    pid = (await state.get_data())["pid"]
    await product_position_manager.update_quantity(pid, qty)
    await state.clear()
    pos = await product_position_manager.get_order_position_by_id(pid)
    text = (f"*Наименование:* {pos['title']}\n"
            f"*Цена:* `{pos['price']}` руб.\n"
            f"*Оставшееся количество:* `{pos['quantity']}` шт")
    await msg.answer("Доступное количество *успешно изменено* ✅", parse_mode="Markdown")
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


@admin_router.callback_query(F.data.startswith("adm-pos:delete:"))
@admin_only
async def adm_pos_delete_confirm(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    try:
        await call.message.edit_text("Вы уверены, что хотите удалить позицию?", reply_markup=admin_confirm_delete(pid))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.callback_query(F.data.startswith("adm-pos:delete-yes:"))
@admin_only
async def adm_pos_delete_yes(call: CallbackQuery, product_position_manager):
    pid = int(call.data.split(":")[2])
    ok, err = await product_position_manager.delete_position(pid)
    if not ok:
        await call.answer(err or "Нельзя удалить позицию, есть заказы, связанные с ней", show_alert=True)
        pos = await product_position_manager.get_order_position_by_id(pid)
        if pos:
            text = (f"*Наименование:* {pos['title']}\n"
                    f"*Цена:* `{pos['price']}` руб.\n"
                    f"*Оставшееся количество:* `{pos['quantity']}` шт")
            await call.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))
        return
    items = await product_position_manager.list_all_order_positions()
    try:
        await call.message.edit_text("Текущие позиции:", reply_markup=admin_positions_list(items))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@admin_router.callback_query(F.data.startswith("adm-pos:") & ~F.data.in_({"adm-pos:add", "adm-pos:back-list"}))
@admin_only
async def adm_pos_detail(call: CallbackQuery, product_position_manager):
    pid = int(call.data.split(":")[1])
    pos = await product_position_manager.get_order_position_by_id(pid)
    if not pos:
        await call.answer("Позиция не найдена", show_alert=True)
        return
    text = (f"*Наименование:* {pos['title']}\n"
            f"*Цена:* `{pos['price']}` руб.\n"
            f"*Оставшееся количество:* `{pos['quantity']}` шт")
    try:
        await call.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


def _admin_summary_text(today_rev: int, awaiting_cnt: int, total_cnt: int, active_cnt: int) -> str:
    return (
        "За сегодня:\n"
        f"Всего заработано: `{today_rev}` руб.\n"
        f"Ожидающих получения: `{awaiting_cnt}` шт.\n"
        f"Всего заказов: `{total_cnt}` шт.\n\n"
        f"Всего ожидаемых заказов: `{active_cnt}`\n"
        f"Общее кол-во заказов: `{total_cnt}`"
    )


def _order_detail_text(o: dict) -> str:
    """
    o: результат admin_get_order(...)
    """
    items = "\n".join(
        f"• {it['title']} ×{it['qty']} — {it['price'] * it['qty']} ₽" for it in o["items"]
    ) or "—"

    way = "Доставка" if o["delivery_way"] == "delivery" else "Самовывоз"
    used = int(o.get("used_bonus") or 0)
    total = int(o.get("total") or 0)
    to_pay = max(total - used, 0)

    dlv_plan = o["delivery_date"].strftime("%d.%m.%Y") if o.get("delivery_date") else "-"
    got_dt = o["finished_at"].strftime("%d.%m.%Y") if o.get("finished_at") else "-"

    is_finished = o["status"] in ("finished", "cancelled")
    header = "*Заказ (завершённый)*" if is_finished else "*Заказ (активный)*"

    text = (
        f"{header}\n\n"
        f"*Имя фамилия:* {o['name_surname']}\n"
        f"*Номер:* {o['tel_num']}\n\n"
        f"*Товары:*\n{items}\n\n"
        f"*Цена:* `{total} ₽`\n"
        f"*Списано бонусов:* `{used} ₽`\n"
        f"*К оплате:* `{to_pay} ₽`\n\n"
        f"*Способ получения:* {way}\n"
        f"*Статус:* {o['status']}\n"
        f"*Дата оформления:* {o['registration_date']:%d.%m.%Y}\n"
        f"*Планируемая дата доставки:* {dlv_plan}\n"
    )
    if o["delivery_way"] == "delivery":
        text += f"*Адрес доставки:* {o.get('delivery_address') or '—'}\n"
    if is_finished:
        text += f"*Дата завершения:* {got_dt}\n"
    return text


@admin_router.callback_query(F.data == "orders")
@admin_only
async def adm_orders_menu(call: CallbackQuery, buyer_order_manager):
    today_rev = await buyer_order_manager.admin_today_revenue()
    awaiting_cnt = await buyer_order_manager.admin_count_awaiting_pickup()
    total_cnt = await buyer_order_manager.admin_count_total()
    active_cnt = await buyer_order_manager.admin_count_active()

    try:
        await call.message.edit_text(
            _admin_summary_text(today_rev, awaiting_cnt, total_cnt, active_cnt),
            parse_mode="Markdown",
            reply_markup=get_admin_orders_keyboard(),
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data == "adm-orders:menu")
@admin_only
async def adm_orders_menu_again(call: CallbackQuery, buyer_order_manager):
    return await adm_orders_menu(call, buyer_order_manager)


@admin_router.callback_query(F.data.in_({"adm-orders:active", "adm-orders:finished"}))
@admin_only
async def adm_orders_list(call: CallbackQuery, buyer_order_manager):
    finished = call.data.endswith("finished")
    orders = await buyer_order_manager.admin_list_orders(finished=finished)
    header = (
        f"Кол-во ожидаемых заказов: `{len(orders)}`"
        if not finished else
        f"Кол-во завершённых заказов: `{len(orders)}`"
    )

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_admin_orders_list_kb(orders, finished),
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data.startswith("adm-orders:back-list:"))
@admin_only
async def adm_orders_back_list(call: CallbackQuery, buyer_order_manager):
    suffix = call.data.split(":")[2]  # 'act' | 'fin'
    finished = (suffix == "fin")
    orders = await buyer_order_manager.admin_list_orders(finished=finished)
    header = (
        f"Кол-во ожидаемых заказов: `{len(orders)}`"
        if not finished else
        f"Кол-во завершённых заказов: `{len(orders)}`"
    )

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_admin_orders_list_kb(orders, finished),
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(
    F.data.startswith("adm-order:") & ~F.data.contains(":advance:") & ~F.data.contains(":cancel")
)
@admin_only
async def adm_order_detail(call: CallbackQuery, buyer_order_manager):
    _, oid, suffix = call.data.split(":")
    order = await buyer_order_manager.admin_get_order(int(oid))
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    kb = admin_order_detail_kb(order, suffix=suffix)
    try:
        await call.message.edit_text(_order_detail_text(order), parse_mode="Markdown", reply_markup=kb)
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data.startswith("adm-order:advance:"))
@admin_only
async def adm_order_advance(call: CallbackQuery, buyer_order_manager):
    _, _, to_status, oid, suffix = call.data.split(":")
    ok = await buyer_order_manager.admin_set_status(int(oid), to_status)
    if not ok:
        await call.answer("Недопустимый переход статуса", show_alert=True)
        return

    order = await buyer_order_manager.admin_get_order(int(oid))
    try:
        await call.message.edit_text(
            _order_detail_text(order),
            parse_mode="Markdown",
            reply_markup=admin_order_detail_kb(order, suffix=suffix),
        )
        await call.answer("Статус обновлён")
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data.startswith("adm-order:cancel:"))
@admin_only
async def adm_order_cancel_confirm(call: CallbackQuery):
    _, _, oid, suffix = call.data.split(":")
    try:
        await call.message.edit_text(
            "Вы уверены, что хотите отменить заказ?",
            reply_markup=admin_cancel_confirm_kb(int(oid), suffix),
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data.startswith("adm-order:cancel-yes:"))
@admin_only
async def adm_order_cancel_yes(call: CallbackQuery, buyer_order_manager):
    _, _, oid, suffix = call.data.split(":")
    ok = await buyer_order_manager.admin_cancel(int(oid))
    if not ok:
        await call.answer("Этот заказ уже нельзя отменить", show_alert=True)
        return

    finished = (suffix == "fin")
    orders = await buyer_order_manager.admin_list_orders(finished=finished)
    header = (
        f"Кол-во ожидаемых заказов: `{len(orders)}`"
        if not finished else
        f"Кол-во завершённых заказов: `{len(orders)}`"
    )

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_admin_orders_list_kb(orders, finished),
        )
        await call.answer("Заказ отменён")
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data == "send-notification")
@admin_only
async def notify_start(call: CallbackQuery, state: FSMContext):
    try:
        await call.message.edit_text(
            "Пришлите сообщение, которое нужно разослать всем пользователям.\n\n"
            "Можно отправить текст или одно вложение (фото/видео/документ) с подписью.\n"
            "_После получения я покажу превью и попрошу подтверждение._",
            parse_mode="Markdown",
            reply_markup=notify_cancel_kb()
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)
        return
    await state.set_state(AdminNotify.waiting_message)


@admin_router.message(AdminNotify.waiting_message)
@admin_only
async def notify_catch_message(msg: Message, state: FSMContext, user_info_manager):
    await state.update_data(src_chat_id=msg.chat.id, src_message_id=msg.message_id)

    total = await user_info_manager.count_all()

    try:
        await msg.answer(
            f"Получил сообщение для рассылки.\n"
            f"Получателей: `{total}`.\n\n"
            f"Нажмите «Разослать», чтобы отправить всем.",
            parse_mode="Markdown",
            reply_markup=notify_confirm_kb()
        )
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, message=msg)
        return

    await state.set_state(AdminNotify.confirm)


@admin_router.callback_query(AdminNotify.confirm, F.data == "notify:redo")
@admin_only
async def notify_redo(call: CallbackQuery, state: FSMContext):
    try:
        await call.message.edit_text(
            "Хорошо, пришлите новое сообщение для рассылки.",
            reply_markup=notify_cancel_kb()
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)
        return
    await state.set_state(AdminNotify.waiting_message)


@admin_router.callback_query(AdminNotify.confirm, F.data == "notify:send")
@admin_only
async def notify_send(call: CallbackQuery, state: FSMContext, user_info_manager):
    data = await state.get_data()
    src_chat_id = data.get("src_chat_id")
    src_message_id = data.get("src_message_id")
    if not src_chat_id or not src_message_id:
        await call.answer("Нет сообщения для рассылки. Пришлите ещё раз.", show_alert=True)
        return

    ids = await user_info_manager.list_all_tg_user_ids()

    ok, fail = 0, 0
    bot = call.message.bot

    for uid in ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=src_chat_id,
                message_id=src_message_id,
            )
            ok += 1
        except TelegramAPIError as e:
            log.warning(f"[Notify] Failed to deliver to {uid}: {e!r}")
            fail += 1
        await asyncio.sleep(0.05)

    await state.clear()

    try:
        await call.message.edit_text(
            f"Рассылка завершена.\nУспешно: `{ok}`, ошибок: `{fail}`.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(True)
        )
        await call.answer("Готово")
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)


@admin_router.callback_query(F.data == "cancel-fsm-admin")
@admin_only
async def notify_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await call.message.edit_text(
            "Действие отменено. Что делаем дальше?",
            reply_markup=get_main_inline_keyboard(True)
        )
        await call.answer()
    except TelegramBadRequest as e:
        log.error(e)
        await handle_telegram_error(e, call=call)
