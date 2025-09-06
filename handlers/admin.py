import asyncio
from contextlib import suppress
from typing import Union

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery

from database.managers.warehouse_manager import WarehouseManager
from database.managers.product_position_manager import ProductPositionManager
from keyboards.admin import (admin_positions_list,
                             admin_edit_back,
                             admin_pos_detail,
                             admin_confirm_delete,
                             get_admin_orders_keyboard,
                             get_admin_orders_list_kb,
                             admin_order_detail_kb,
                             admin_cancel_confirm_kb, notify_cancel_kb,
                             notify_confirm_kb, admin_warehouse_detail_kb,
                             admin_create_warehouse_kb
                             )
from keyboards.client import get_main_inline_keyboard, confirm_geoposition_kb
from api.yandex_delivery import geocode_address

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
    add_weight = State()  # Вес
    add_length = State()  # Длина
    add_width = State()  # Ширина
    add_height = State()  # Высота

    edit_title = State()
    edit_price = State()
    edit_qty = State()
    edit_weight = State()
    edit_dims = State()


class AdminNotify(StatesGroup):
    waiting_message = State()
    confirm = State()


class WarehouseEdit(StatesGroup):
    waiting_for_value = State()
    waiting_for_location = State()


class WarehouseCreate(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    confirm_geoposition = State()
    waiting_for_porch = State()
    waiting_for_floor = State()
    waiting_for_apartment = State()
    waiting_for_contact_name = State()
    waiting_for_contact_phone = State()


def format_product_info(pos: dict) -> str:
    """Форматирует детальную информацию о товаре."""
    if not pos:
        return "Товар не найден."
    return (
        f"*Наименование:* {pos['title']}\n"
        f"*Цена:* `{pos['price']}` руб.\n"
        f"*Количество:* `{pos['quantity']}` шт.\n"
        f"*Вес:* `{pos.get('weight_kg', 'не указ.')}` кг.\n"
        f"*Габариты (ДxШxВ):* `{pos.get('length_m', '?')} x {pos.get('width_m', '?')} x {pos.get('height_m', '?')}` м."
    )


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
async def adm_pos_add_qty(msg: Message, state: FSMContext):
    try:
        qty = int(msg.text)
        assert qty >= 0
    except Exception:
        await msg.answer("Количество должно быть целым числом ≥ 0.")
        return

    await state.update_data(qty=qty)
    # Переходим к следующему шагу - вводу веса
    await state.set_state(PosEdit.add_weight)
    await msg.answer("Введите *вес* одной единицы товара в килограммах (например: 0.5):", parse_mode="Markdown")


async def _parse_float(text: str) -> Union[float, None]:
    """Вспомогательная функция для парсинга положительных float чисел."""
    try:
        value = float(text.replace(',', '.'))  # Заменяем запятую на точку для удобства
        if value < 0:
            return None
        return value
    except (ValueError, TypeError):
        return None


@admin_router.message(PosEdit.add_weight)
@admin_only
async def adm_pos_add_weight(msg: Message, state: FSMContext):
    weight = await _parse_float(msg.text)
    if weight is None:
        await msg.answer("Вес должен быть положительным числом (например: 0.5 или 1.2).")
        return
    await state.update_data(weight_kg=weight)
    await state.set_state(PosEdit.add_length)
    await msg.answer("Введите *длину* в метрах (например: 0.2):", parse_mode="Markdown")


@admin_router.message(PosEdit.add_length)
@admin_only
async def adm_pos_add_length(msg: Message, state: FSMContext):
    length = await _parse_float(msg.text)
    if length is None:
        await msg.answer("Длина должна быть положительным числом (например: 0.2 или 1.0).")
        return
    await state.update_data(length_m=length)
    await state.set_state(PosEdit.add_width)
    await msg.answer("Введите *ширину* в метрах (например: 0.15):", parse_mode="Markdown")


@admin_router.message(PosEdit.add_width)
@admin_only
async def adm_pos_add_width(msg: Message, state: FSMContext):
    width = await _parse_float(msg.text)
    if width is None:
        await msg.answer("Ширина должна быть положительным числом (например: 0.15).")
        return
    await state.update_data(width_m=width)
    await state.set_state(PosEdit.add_height)
    await msg.answer("Введите *высоту* в метрах (например: 0.1):", parse_mode="Markdown")


@admin_router.message(PosEdit.add_height)
@admin_only
async def adm_pos_add_height_and_create(msg: Message, state: FSMContext, product_position_manager):
    height = await _parse_float(msg.text)
    if height is None:
        await msg.answer("Высота должна быть положительным числом (например: 0.1).")
        return

    data = await state.get_data()

    # Вызываем обновленный метод создания позиции
    pid = await product_position_manager.create_position(
        title=data["title"],
        price=data["price"],
        quantity=data["qty"],
        weight_kg=data["weight_kg"],
        length_m=data["length_m"],
        width_m=data["width_m"],
        height_m=height  # Последний параметр берем напрямую
    )
    await state.clear()

    pos = await product_position_manager.get_order_position_by_id(pid)

    # Обновляем текст вывода, чтобы показать новые данные
    text = format_product_info(pos)

    await msg.answer("Позиция *успешно добавлена* ✅", parse_mode="Markdown")
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


@admin_router.callback_query(F.data.startswith("adm-pos:edit-title:"))
@admin_only
async def adm_pos_edit_title_start(call: CallbackQuery, state: FSMContext):
    """
    Реагирует на кнопку 'Изменить название' и запускает FSM.
    """
    try:
        pid = int(call.data.split(":")[2])
    except (ValueError, IndexError):
        await call.answer("Ошибка в данных кнопки.", show_alert=True)
        return

    await state.update_data(pid=pid)
    await state.set_state(PosEdit.edit_title)
    try:
        await call.message.edit_text(
            "Введите *новое название* позиции:",
            parse_mode="Markdown",
            reply_markup=admin_edit_back(pid)
        )
        await call.answer()
    except TelegramBadRequest as e:
        await handle_telegram_error(e, call=call)


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

    # Обновляем текст вывода, чтобы показать новые данные
    text = format_product_info(pos)
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

    # Обновляем текст вывода, чтобы показать новые данные
    text = format_product_info(pos)
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


@admin_router.callback_query(F.data.startswith("adm-pos:edit-weight:"))
@admin_only
async def adm_pos_edit_weight_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[2])
    await state.update_data(pid=pid)
    await state.set_state(PosEdit.edit_weight)
    await call.message.edit_text(
        "Введите *новый вес* товара в килограммах (например: 0.5):",
        parse_mode="Markdown",
        reply_markup=admin_edit_back(pid)
    )
    await call.answer()


@admin_router.message(PosEdit.edit_weight)
@admin_only
async def adm_pos_edit_weight_set(msg: Message, state: FSMContext, product_position_manager: ProductPositionManager):
    weight = await _parse_float(msg.text)  # Используем нашу вспомогательную функцию
    if weight is None:
        await msg.answer("Вес должен быть положительным числом.")
        return

    data = await state.get_data()
    pid = data["pid"]
    await product_position_manager.update_weight(pid, weight)  # Нужен новый метод в менеджере
    await state.clear()

    await msg.answer("✅ Вес товара успешно изменен!")

    # Показываем обновленную карточку товара
    pos = await product_position_manager.get_order_position_by_id(pid)
    text = format_product_info(pos)  # Выносим форматирование в отдельную функцию
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


# --- Редактирование Габаритов ---

@admin_router.callback_query(F.data.startswith("adm-pos:edit-dims:"))
@admin_only
async def adm_pos_edit_dims_start(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[2])
    await state.update_data(pid=pid)
    await state.set_state(PosEdit.edit_dims)
    await call.message.edit_text(
        "Введите *новые габариты* (Длина x Ширина x Высота) в метрах, через пробел или 'x'.\n\n"
        "Пример: `0.2 x 0.15 x 0.1`",
        parse_mode="Markdown",
        reply_markup=admin_edit_back(pid)
    )
    await call.answer()


@admin_router.message(PosEdit.edit_dims)
@admin_only
async def adm_pos_edit_dims_set(msg: Message, state: FSMContext, product_position_manager: ProductPositionManager):
    # Пытаемся распарсить три числа из строки
    try:
        # Заменяем 'x', 'х' (русскую) и запятые, чтобы быть гибкими к вводу
        cleaned_text = msg.text.replace(',', '.').replace('x', ' ').replace('х', ' ')
        dims = [float(d.strip()) for d in cleaned_text.split()]
        if len(dims) != 3:
            raise ValueError
        length, width, height = dims
        if not all(d > 0 for d in dims):
            raise ValueError
    except (ValueError, TypeError, IndexError):
        await msg.answer("Неверный формат. Пожалуйста, введите три положительных числа, например: `0.2 0.15 0.1`")
        return

    data = await state.get_data()
    pid = data["pid"]
    await product_position_manager.update_dims(pid, length, width, height)  # Нужен новый метод в менеджере
    await state.clear()

    await msg.answer("✅ Габариты товара успешно изменены!")

    pos = await product_position_manager.get_order_position_by_id(pid)
    text = format_product_info(pos)
    await msg.answer(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))


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

    # Обновляем текст вывода, чтобы показать новые данные
    text = format_product_info(pos)
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
            # Обновляем текст вывода, чтобы показать новые данные
            text = format_product_info(pos)
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


def format_warehouse_info(warehouse_data: dict) -> str:
    """Вспомогательная функция для красивого вывода информации о складе."""
    if not warehouse_data:
        return (
            "❗️ Склад по умолчанию не найден в базе данных.\n\n"
            "Доставка не будет работать, пока вы не создадите запись о складе ")

    address_line = warehouse_data.get('address', 'не указан')
    details = []
    if warehouse_data.get('porch'):
        details.append(f"подъезд {warehouse_data['porch']}")
    if warehouse_data.get('floor'):
        details.append(f"этаж {warehouse_data['floor']}")
    if warehouse_data.get('apartment'):
        details.append(f"кв/офис {warehouse_data['apartment']}")
    if details:
        address_line += f" ({', '.join(details)})"

    return (
        "🚚 Информация о складе для отправки заказов:\n\n"
        f"Название: {warehouse_data.get('name', 'не указано')}\n"
        f"Адрес: {address_line}\n"
        f"Контактное лицо: {warehouse_data.get('contact_name', 'не указано')}\n"
        f"Телефон: {warehouse_data.get('contact_phone', 'не указан')}"
        f"Координаты (шир, долг): <code>{warehouse_data.get('latitude')},"
        f" {warehouse_data.get('longitude')}"
    )


# --- Хендлер для кнопки "Настройки доставки" ---
@admin_router.callback_query(F.data == "delivery-settings")
@admin_only
async def admin_delivery_settings(call: CallbackQuery, warehouse_manager: WarehouseManager):
    """
    Показывает информацию о складе или предлагает его создать.
    """
    await call.answer()
    default_warehouse = await warehouse_manager.get_default_warehouse()

    if default_warehouse:
        # Склад найден, показываем детали и кнопки редактирования (старая логика)
        text = format_warehouse_info(default_warehouse)
        kb = admin_warehouse_detail_kb(default_warehouse['id'])
    else:
        # Склад НЕ найден, показываем ошибку и кнопку "Создать"
        text = format_warehouse_info(None)  # Функция вернет текст ошибки
        kb = admin_create_warehouse_kb()

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- Хендлер для кнопок "Изменить..." ---
@admin_router.callback_query(F.data.startswith("wh:edit:"))
@admin_only
async def start_edit_warehouse_field(call: CallbackQuery, state: FSMContext):
    """
    Запускает FSM для редактирования одного поля склада.
    """
    await call.answer()
    try:
        _, _, field_to_edit, warehouse_id_str = call.data.split(":")
        warehouse_id = int(warehouse_id_str)
    except ValueError:
        await call.message.answer("Ошибка: некорректные данные в кнопке.")
        return

    if field_to_edit == "location":
        await state.set_state(WarehouseEdit.waiting_for_location)
        await state.update_data(warehouse_id=warehouse_id)
        await call.message.edit_text(
            "Отправьте мне геолокацию склада (через скрепку 📎 -> Геопозиция)."
        )
        return

    # --- ИЗМЕНЕНИЕ ЗДЕСЬ: ДОБАВЛЯЕМ НОВЫЕ ПОЛЯ В field_map ---
    field_map = {
        "name": "название склада",
        "address": "основной адрес (улица, дом)",
        "porch": "подъезд",
        "floor": "этаж",
        "apartment": "номер квартиры/офиса",
        "contact_name": "имя контактного лица",
        "contact_phone": "контактный телефон"
    }

    prompt_text = field_map.get(field_to_edit)
    if not prompt_text:
        await call.message.answer("Ошибка: попытка редактировать неизвестное поле.")
        return

    await state.set_state(WarehouseEdit.waiting_for_value)
    await state.update_data(field_to_edit=field_to_edit, warehouse_id=warehouse_id)

    # Используем parse_mode="HTML" для жирного шрифта
    await call.message.edit_text(f"Введите новое значение для поля '<b>{prompt_text}</b>':", parse_mode="HTML")


# --- Хендлер, который ловит ответ от админа с новым значением ---
@admin_router.message(WarehouseEdit.waiting_for_value)
@admin_only
async def process_edit_warehouse_value(msg: Message, state: FSMContext, warehouse_manager: WarehouseManager):
    """
    Получает новое значение, обновляет его в БД и показывает результат.
    """
    data = await state.get_data()
    field = data.get("field_to_edit")
    warehouse_id = data.get("warehouse_id")
    new_value = msg.text.strip()

    await warehouse_manager.update_field(warehouse_id, field, new_value)

    await state.clear()
    await msg.answer("✅ Данные склада успешно обновлены!")

    default_warehouse = await warehouse_manager.get_default_warehouse()
    text = format_warehouse_info(default_warehouse)
    kb = admin_warehouse_detail_kb(default_warehouse['id']) if default_warehouse else None
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@admin_router.message(WarehouseEdit.waiting_for_location, F.location)
@admin_only
async def process_edit_warehouse_location(msg: Message, state: FSMContext, warehouse_manager: WarehouseManager):
    """
    Ловит геолокацию, обновляет широту и долготу в БД.
    """
    data = await state.get_data()
    warehouse_id = data.get("warehouse_id")

    latitude = msg.location.latitude
    longitude = msg.location.longitude

    # Вызываем новый метод в менеджере для обновления координат
    await warehouse_manager.update_location(warehouse_id, latitude, longitude)

    await state.clear()
    await msg.answer("✅ Координаты склада успешно обновлены!")

    # Показываем админу обновленную информацию
    default_warehouse = await warehouse_manager.get_default_warehouse()
    text = format_warehouse_info(default_warehouse)
    kb = admin_warehouse_detail_kb(default_warehouse['id']) if default_warehouse else None
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("adm-pos:") & ~F.data.in_({"adm-pos:add", "adm-pos:back-list"}))
@admin_only
async def adm_pos_detail(call: CallbackQuery, product_position_manager):
    pid = int(call.data.split(":")[1])
    pos = await product_position_manager.get_order_position_by_id(pid)
    if not pos:
        await call.answer("Позиция не найдена", show_alert=True)
        return

    # Формируем новый, расширенный текст
    text = format_product_info(pos)
    try:
        await call.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_pos_detail(pid))
        await call.answer()
    except TelegramBadRequest as e:
        await handle_telegram_error(e, call=call)
        return


# =======================================================================================
# ======================== НОВЫЙ БЛОК СОЗДАНИЯ СКЛАДА ===================================
# =======================================================================================

@admin_router.callback_query(F.data == "wh:create")
@admin_only
async def start_create_warehouse(call: CallbackQuery, state: FSMContext):
    """Начинает FSM для создания склада."""
    await state.set_state(WarehouseCreate.waiting_for_name)
    await call.message.edit_text(
        "**Шаг 1/7:** Введите **название** склада (например, 'Основной склад'):", parse_mode="Markdown")
    await call.answer()


@admin_router.message(WarehouseCreate.waiting_for_name)
@admin_only
async def process_create_warehouse_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(WarehouseCreate.waiting_for_address)
    await msg.answer(
        "**Шаг 2/7:** Теперь введите **адрес** склада (город, улица, дом) или сразу отправьте его **геолокацию**.",
        parse_mode="Markdown")


@admin_router.message(WarehouseCreate.waiting_for_address, F.text)
@admin_only
async def process_create_warehouse_text_address(msg: Message, state: FSMContext, bot: Bot):
    """Ловит текстовый адрес, геокодирует и отправляет карту для подтверждения."""
    address_text = msg.text.strip()
    await msg.answer("⏳ Ищу адрес на карте...")

    coords = await geocode_address(address_text)
    if not coords:
        await msg.answer("Не удалось найти такой адрес. Попробуйте ввести его подробнее или отправьте геоточку.")
        return

    lon, lat = coords
    await state.update_data(address=address_text, latitude=lat, longitude=lon)
    await state.set_state(WarehouseCreate.confirm_geoposition)

    await bot.send_location(chat_id=msg.chat.id, latitude=lat, longitude=lon)
    await msg.answer("Я нашел склад здесь. Местоположение верное?", reply_markup=confirm_geoposition_kb())


@admin_router.message(WarehouseCreate.waiting_for_address, F.location)
@admin_router.message(WarehouseCreate.confirm_geoposition, F.location)
@admin_only
async def process_create_warehouse_manual_location(msg: Message, state: FSMContext):
    """Ловит геолокацию, отправленную вручную."""
    await state.update_data(
        latitude=msg.location.latitude,
        longitude=msg.location.longitude,
        address=f"Геометка ({msg.location.latitude:.5f}, {msg.location.longitude:.5f})"
    )
    await state.set_state(WarehouseCreate.waiting_for_porch)
    await state.set_state(WarehouseCreate.waiting_for_porch)
    await msg.answer(
        "**Шаг 3/7:** Точка принята! Теперь введите **подъезд** (или отправьте прочерк `-`, если его нет):",
        parse_mode="Markdown")


@admin_router.callback_query(WarehouseCreate.confirm_geoposition, F.data.startswith("geo:"))
@admin_only
async def process_create_warehouse_geoposition_confirm(call: CallbackQuery, state: FSMContext):
    """Обрабатывает подтверждение геоточки."""
    await call.answer()
    action = call.data.split(":")[1]

    with suppress(TelegramBadRequest):
        await call.message.delete()
        await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id - 1)

    if action == "confirm":
        await state.set_state(WarehouseCreate.waiting_for_porch)
        await call.message.answer(
            "**Шаг 3/7:** Отлично! Теперь введите **подъезд** (или отправьте прочерк `-`, если его нет):",
            parse_mode="Markdown")
        return

    if action == "manual":
        await call.message.answer("Хорошо, пожалуйста, отправьте мне геолокацию склада (Скрепка 📎 -> Местоположение).")


@admin_router.message(WarehouseCreate.waiting_for_porch)
@admin_only
async def process_create_warehouse_porch(msg: Message, state: FSMContext):
    await state.update_data(porch=msg.text.strip() if msg.text.strip() != '-' else None)
    await state.set_state(WarehouseCreate.waiting_for_floor)
    await msg.answer("Шаг 4/7: Принято. Введите **этаж** (или `-`):", parse_mode="Markdown")


@admin_router.message(WarehouseCreate.waiting_for_floor)
@admin_only
async def process_create_warehouse_floor(msg: Message, state: FSMContext):
    await state.update_data(floor=msg.text.strip() if msg.text.strip() != '-' else None)
    await state.set_state(WarehouseCreate.waiting_for_apartment)
    await msg.answer("Шаг 5/7: Принято. Введите **номер квартиры/офиса** (или `-`):", parse_mode="Markdown")


@admin_router.message(WarehouseCreate.waiting_for_apartment)
@admin_only
async def process_create_warehouse_apartment(msg: Message, state: FSMContext):
    await state.update_data(apartment=msg.text.strip() if msg.text.strip() != '-' else None)
    await state.set_state(WarehouseCreate.waiting_for_contact_name)
    await msg.answer("**Шаг 6/7:** Адрес полностью собран! Теперь введите **имя контактного лица**:",
                     parse_mode="Markdown")


@admin_router.message(WarehouseCreate.waiting_for_contact_name)
@admin_only
async def process_create_warehouse_contact_name(msg: Message, state: FSMContext):
    await state.update_data(contact_name=msg.text.strip())
    await state.set_state(WarehouseCreate.waiting_for_contact_phone)
    await msg.answer("**Шаг 7/7:** И последнее: введите **контактный телефон** склада:", parse_mode="Markdown")


@admin_router.message(WarehouseCreate.waiting_for_contact_phone)
@admin_only
async def process_create_warehouse_contact_phone_and_save(msg: Message, state: FSMContext,
                                                          warehouse_manager: WarehouseManager):
    await state.update_data(contact_phone=msg.text.strip())
    data = await state.get_data()
    await state.clear()

    # Вызываем обновленный метод, который сохранит все поля
    new_warehouse_id = await warehouse_manager.create_default_warehouse(data)

    await msg.answer("✅ Склад по умолчанию успешно создан и сохранен!")

    # Показываем результат
    new_warehouse_data = await warehouse_manager.get_default_warehouse()
    text = format_warehouse_info(new_warehouse_data)  # <-- Нужно будет обновить и эту функцию
    kb = admin_warehouse_detail_kb(new_warehouse_id)  # <-- И эту клавиатуру
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb)
