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


def get_orders_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Активные", callback_data="orders-active")],
            [InlineKeyboardButton(text="Завершённые", callback_data="orders-finished")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back-main")],
        ]
    )


def get_orders_list_kb(orders: list, finished: bool):
    suffix = "fin" if finished else "act"
    kb = [
        [InlineKeyboardButton(
            text=f"#{o.id} ({o.registration_date:%d.%m})",  # TODO: подумать над отображением
            callback_data=f"order:{o.id}:{suffix}"
        )] for o in orders
    ]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back-orders-menu:{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_order_detail_kb(order):
    finished = order.status in ("finished", "cancelled")
    suffix = "fin" if finished else "act"

    rows: list[list[InlineKeyboardButton]] = []
    if not finished:
        rows.append([InlineKeyboardButton(
            text="❌ Отмена заказа", callback_data=f"order-cancel:{order.id}:{suffix}"
        )])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back-to-list:{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_cancel_confirm_kb(order_id: int, suffix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ДА", callback_data=f"cancel-yes:{order_id}:{suffix}")],
            [InlineKeyboardButton(text="ОСТАВИТЬ", callback_data=f"cancel-no:{order_id}:{suffix}")],
        ]
    )


def get_all_products(products: list[dict], cart: dict[int, int]) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        pid = p["id"]
        qty = cart.get(pid, 0)
        check = "✅" if qty > 0 else "🟩"
        title = f"{check} {p['title']} — {p['price']} руб."

        toggle_cb = f"cart:toggle:{pid}" if p["quantity"] > 0 else "noop"
        rows.append([InlineKeyboardButton(text=title, callback_data=toggle_cb)])

        if qty > 0:
            minus_cb = f"cart:sub:{pid}"
            plus_cb = f"cart:add:{pid}" if qty < p["quantity"] else "noop"
            rows.append([
                InlineKeyboardButton(text="➖", callback_data=minus_cb),
                InlineKeyboardButton(text=f"{qty} шт (доступно {p['quantity']})", callback_data="noop"),
                InlineKeyboardButton(text="➕", callback_data=plus_cb),
            ])

    rows.append([InlineKeyboardButton(text="Готово", callback_data="cart:done")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back-main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choice_of_delivery() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Самовывоз", callback_data="del:pickup")],
        [InlineKeyboardButton(text="Доставка", callback_data="del:delivery")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="cart:back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_address_select(saved: str | None) -> InlineKeyboardMarkup:
    rows = []
    if saved:
        rows.append([InlineKeyboardButton(text=f"Использовать адрес: {saved}", callback_data="addr:use_saved")])
    rows.append([InlineKeyboardButton(text="Ввести адрес вручную", callback_data="addr:enter")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="addr:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_create_order(bonuses: int, used_bonuses: int) -> InlineKeyboardMarkup:
    rows = []
    if bonuses > 0 and used_bonuses == 0:
        rows.append([
            InlineKeyboardButton(text=f"Списать бонусы ({bonuses} ₽)", callback_data="bonus:use"),

        ])
    else:
        rows.append([
            InlineKeyboardButton(text="Оставить бонусы", callback_data="bonus:skip"),
        ])
    rows.append([InlineKeyboardButton(text="✅ Всё верно", callback_data="confirm:ok")])
    rows.append([InlineKeyboardButton(text="Начать заново", callback_data="confirm:restart")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="addr:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_profile_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить имя и фамилию", callback_data="profile:edit-name")],
        [InlineKeyboardButton(text="Изменить номер телефона", callback_data="profile:edit-phone")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back-main")],
    ])
