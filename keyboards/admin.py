from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.statuses import S_WAITING, S_READY, S_TRANSFERRING, S_FINISHED


def admin_positions_list(positions: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in positions:
        title = f"{p['title']} — {p['price']} руб, {p['quantity']} шт"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"adm-pos:{p['id']}")])
    rows.append([InlineKeyboardButton(text="Добавить", callback_data="adm-pos:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back-admin-main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pos_detail(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить название", callback_data=f"adm-pos:edit-title:{pid}")],
        [InlineKeyboardButton(text="Изменить цену", callback_data=f"adm-pos:edit-price:{pid}")],
        [InlineKeyboardButton(text="Изменить количество", callback_data=f"adm-pos:edit-qty:{pid}")],
        [InlineKeyboardButton(text="Изменить вес", callback_data=f"adm-pos:edit-weight:{pid}")],
        [InlineKeyboardButton(text="Изменить габариты", callback_data=f"adm-pos:edit-dims:{pid}")],
        [InlineKeyboardButton(text="Удалить", callback_data=f"adm-pos:delete:{pid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm-pos:back-list")],
    ])


def admin_confirm_delete(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ДА", callback_data=f"adm-pos:delete-yes:{pid}")],
        [InlineKeyboardButton(text="ОСТАВИТЬ", callback_data=f"adm-pos:{pid}")],
    ])


def admin_edit_back(pid: int | None = None) -> InlineKeyboardMarkup:
    cb = f"adm-pos:{pid}" if pid else "positions"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=cb)]
    ])


def get_admin_orders_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Активные", callback_data="adm-orders:active")],
        [InlineKeyboardButton(text="Завершённые", callback_data="adm-orders:finished")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back-admin-main")],
    ])


def get_admin_orders_list_kb(orders: list[dict], finished: bool) -> InlineKeyboardMarkup:
    suffix = "fin" if finished else "act"
    rows = [
        [InlineKeyboardButton(
            text=f"#{o['id']} ({o['registration_date']:%d.%m})",
            callback_data=f"adm-order:{o['id']}:{suffix}"
        )]
        for o in orders
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm-orders:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_detail_kb(order: dict, *, suffix: str) -> InlineKeyboardMarkup:
    st, way = order["status"], order["delivery_way"]
    rows: list[list[InlineKeyboardButton]] = []

    if st == S_WAITING:
        to_status = S_READY if way == "pickup" else S_TRANSFERRING
        text = "Готов к получению" if way == "pickup" else "Передано в доставку"
        rows.append([InlineKeyboardButton(text=text,
                                          callback_data=f"adm-order:advance:{to_status}:{order['id']}:{suffix}")])

    if (st == S_READY and way == "pickup") or (st == S_TRANSFERRING and way == "delivery"):
        rows.append([InlineKeyboardButton(text="Завершить",
                                          callback_data=f"adm-order:advance:{S_FINISHED}:{order['id']}:{suffix}")])

    if st in (S_WAITING, S_READY):
        rows.append([InlineKeyboardButton(text="❌ Отмена заказа",
                                          callback_data=f"adm-order:cancel:{order['id']}:{suffix}")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm-orders:back-list:{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel_confirm_kb(order_id: int, suffix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ДА", callback_data=f"adm-order:cancel-yes:{order_id}:{suffix}")],
        [InlineKeyboardButton(text="ОСТАВИТЬ", callback_data=f"adm-order:{order_id}:{suffix}")],
    ])


def notify_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel-fsm-admin")]
    ])


def notify_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Разослать", callback_data="notify:send")],
        [InlineKeyboardButton(text="⬅️ Изменить", callback_data="notify:redo")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel-fsm-admin")],
    ])


def admin_warehouse_detail_kb(warehouse_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для детального просмотра и редактирования склада."""
    builder = InlineKeyboardBuilder()

    builder.button(text="📝 Изменить Название", callback_data=f"wh:edit:name:{warehouse_id}")
    builder.button(text="📝 Изменить Адрес", callback_data=f"wh:edit:address:{warehouse_id}")
    builder.button(text="📝 Изменить Подъезд", callback_data=f"wh:edit:porch:{warehouse_id}")
    builder.button(text="📝 Изменить Этаж", callback_data=f"wh:edit:floor:{warehouse_id}")
    builder.button(text="📝 Изменить Кв./Офис", callback_data=f"wh:edit:apartment:{warehouse_id}")
    builder.button(text="📝 Изменить Контактное лицо", callback_data=f"wh:edit:contact_name:{warehouse_id}")
    builder.button(text="📝 Изменить Телефон", callback_data=f"wh:edit:contact_phone:{warehouse_id}")
    # --- НОВАЯ КНОПКА ---
    builder.button(text="📍 Обновить Координаты", callback_data=f"wh:edit:location:{warehouse_id}")

    builder.button(text="⬅️ Назад в админ-меню", callback_data="back-admin-main")
    builder.adjust(1)
    return builder.as_markup()


def admin_create_warehouse_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура, предлагающая создать склад по умолчанию, если он не найден.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать склад по умолчанию", callback_data="wh:create")
    builder.button(text="⬅️ Назад в админ-меню", callback_data="back-admin-main")
    builder.adjust(1)
    return builder.as_markup()
