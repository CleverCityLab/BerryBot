from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.statuses import S_WAITING, S_READY, S_TRANSFERRING, S_FINISHED, S_PROCESSING, S_CANCELLED


def admin_positions_list(
        positions: list[dict],
        page: int = 1,
        page_size: int = 50,
) -> InlineKeyboardMarkup:
    total = len(positions)
    total_pages = max(1, ceil(total / page_size))
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    end = start + page_size
    page_positions = positions[start:end]

    rows: list[list[InlineKeyboardButton]] = []

    for p in page_positions:
        title = f"{p['title']} — {p['price']} руб, {p['quantity']} шт"
        rows.append([InlineKeyboardButton(text=title, callback_data=f"adm-pos:{p['id']}")])

    if total_pages > 1:
        prev_page = page - 1 if page > 1 else 1
        next_page = page + 1 if page < total_pages else total_pages
        rows.append([
            InlineKeyboardButton(text="«", callback_data="positions:page:1" if page > 1 else "noop"),
            InlineKeyboardButton(text="‹", callback_data=f"positions:page:{prev_page}" if page > 1 else "noop"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="›",
                                 callback_data=f"positions:page:{next_page}" if page < total_pages else "noop"),
            InlineKeyboardButton(text="»",
                                 callback_data=f"positions:page:{total_pages}" if page < total_pages else "noop"),
        ])

    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data="adm-pos:add")])
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


def get_admin_orders_list_kb(
        orders: list[dict],
        finished: bool,
        page: int = 1,
        page_size: int = 50,
) -> InlineKeyboardMarkup:
    total = len(orders)
    total_pages = max(1, ceil(total / page_size))
    page = max(1, min(page, total_pages))  # clamp

    start = (page - 1) * page_size
    end = start + page_size
    page_orders = orders[start:end]

    status_token = "finished" if finished else "active"
    suffix = "fin" if finished else "act"

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"#{o['id']} ({o['registration_date']:%d.%m})",
                callback_data=f"adm-order:{o['id']}:{suffix}",
            )
        ]
        for o in page_orders
    ]

    if total_pages > 1:
        prev_page = page - 1 if page > 1 else 1
        next_page = page + 1 if page < total_pages else total_pages
        rows.append([
            InlineKeyboardButton(text="«", callback_data=f"adm-orders:page:{status_token}:1" if page > 1 else "noop"),
            InlineKeyboardButton(text="‹",
                                 callback_data=f"adm-orders:page:{status_token}:{prev_page}" if page > 1 else "noop"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="›",
                                 callback_data=f"adm-orders:page:{status_token}:{next_page}"
                                 if page < total_pages else "noop"),
            InlineKeyboardButton(text="»",
                                 callback_data=f"adm-orders:page:{status_token}:{total_pages}"
                                 if page < total_pages else "noop"),
        ])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm-orders:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_order_detail_kb(order: dict, *, suffix: str) -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для детального просмотра заказа в админ-панели.
    Кнопки зависят от текущего статуса заказа.
    """
    builder = InlineKeyboardBuilder()
    status = order["status"]
    delivery_way = order["delivery_way"]
    order_id = order["id"]

    # --- НОВАЯ, УЛУЧШЕННАЯ ЛОГИКА ОТОБРАЖЕНИЯ КНОПОК ---

    # Если заказ оплачен и находится в обработке (S_PROCESSING),
    # админ должен решить, что с ним делать дальше.
    if status == S_PROCESSING:
        if delivery_way == "pickup":
            # Для самовывоза предлагаем пометить "Готов к выдаче"
            builder.button(
                text="✅ Готов к выдаче",
                callback_data=f"adm-order:advance:{S_READY}:{order_id}:{suffix}"
            )

    # Если заказ готов к самовывозу или уже передан в доставку,
    # предлагаем его "Завершить".
    if (status == S_READY and delivery_way == "pickup") or (status == S_TRANSFERRING and delivery_way == "delivery"):
        builder.button(
            text="🏁 Завершить заказ",
            callback_data=f"adm-order:advance:{S_FINISHED}:{order_id}:{suffix}"
        )

    # Отменить можно любой активный заказ, который еще не в пути и не готов
    if status in (S_WAITING, S_PROCESSING, S_READY):
        builder.button(
            text="❌ Отменить заказ",
            callback_data=f"adm-order:cancel:{order_id}:{suffix}"
        )

    # Если это заказ с доставкой и есть заявка в Яндексе, добавляем кнопку обновления
    if delivery_way == "delivery" and status not in (S_FINISHED, S_CANCELLED):
        builder.button(
            text="🔄 Обновить статус доставки",
            callback_data=f"delivery:refresh:{order_id}"
        )

    # Кнопка "Назад" есть всегда
    builder.button(text="⬅️ Назад к списку", callback_data=f"adm-orders:back-list:{suffix}")

    builder.adjust(1)  # Каждая кнопка на своей строке
    return builder.as_markup()


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


def admin_manage_admins_kb(admins: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура для управления списком администраторов."""
    builder = InlineKeyboardBuilder()

    # Создаем кнопки для удаления каждого админа
    for admin in admins:
        builder.button(
            text=f"❌ Удалить {admin['full_name']} ({admin['id']})",
            callback_data=f"admin:manage:delete:{admin['id']}"
        )

    # Кнопки для основных действий
    builder.button(text="➕ Добавить администратора", callback_data="admin:manage:add")
    builder.button(text="⬅️ Назад в админ-меню", callback_data="back-admin-main")

    builder.adjust(1)  # Каждая кнопка на новой строке
    return builder.as_markup()


def admin_confirm_delete_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения удаления администратора."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, я уверен", callback_data=f"admin:manage:delete_confirm:{user_id}")
    builder.button(text="⬅️ Нет, назад", callback_data="admin:manage")
    builder.adjust(1)
    return builder.as_markup()


def admin_manage_add_back_kb() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой "Назад" для меню добавления администратора."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:manage")
    return builder.as_markup()
