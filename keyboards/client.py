from math import ceil

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models.buyer_orders import BuyerOrders


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
            [InlineKeyboardButton(text="Настройки доставки", callback_data="delivery-settings")],
            [InlineKeyboardButton(text="Управление админами", callback_data="admin:manage")],
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


def get_orders_list_kb(
        orders: list,
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

    suffix = "fin" if finished else "act"

    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=f"#{o.id} ({o.registration_date:%d.%m})",  # TODO: подумать над отображением
            callback_data=f"order:{o.id}:{suffix}"
        )]
        for o in page_orders
    ]

    if total_pages > 1:
        prev_page = page - 1 if page > 1 else 1
        next_page = page + 1 if page < total_pages else total_pages
        kb.append([
            InlineKeyboardButton(text="«", callback_data=f"orders:page:{suffix}:1" if page > 1 else "noop"),
            InlineKeyboardButton(text="‹", callback_data=f"orders:page:{suffix}:{prev_page}" if page > 1 else "noop"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="›",
                                 callback_data=f"orders:page:{suffix}:{next_page}" if page < total_pages else "noop"),
            InlineKeyboardButton(text="»",
                                 callback_data=f"orders:page:{suffix}:{total_pages}" if page < total_pages else "noop"),
        ])

    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back-orders-menu:{suffix}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_order_detail_kb(order: BuyerOrders) -> InlineKeyboardMarkup:  # Убедитесь, что принимаете объект
    builder = InlineKeyboardBuilder()

    # Показываем кнопку, только если это активный заказ с доставкой и уже есть заявка в Яндексе
    if order.delivery_way.value == 'delivery' and order.yandex_claim_id and order.status.value not in (
            'finished', 'cancelled'):
        builder.button(
            text="🔄 Обновить статус доставки",
            callback_data=f"delivery:refresh:{order.id}")

    if order.status.value not in ('finished', 'cancelled'):
        builder.button(text="❌ Отмена заказа", callback_data=f"order-cancel:{order.id}:act")

    builder.button(text="⬅️ Назад к списку",
                   callback_data=f"back-to-list:{'fin' if order.status.value in ('finished', 'cancelled') else 'act'}")

    builder.adjust(1)  # Каждая кнопка на новой строке
    return builder.as_markup()


def get_cancel_confirm_kb(order_id: int, suffix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="ДА", callback_data=f"cancel-yes:{order_id}:{suffix}")],
            [InlineKeyboardButton(text="ОСТАВИТЬ", callback_data=f"cancel-no:{order_id}:{suffix}")],
        ]
    )


def get_all_products(
        products: list[dict],
        cart: dict[int, int],
        page: int = 1,
        page_size: int = 20,
) -> InlineKeyboardMarkup:
    total = len(products)
    total_pages = max(1, ceil(total / page_size))
    page = max(1, min(page, total_pages))  # clamp

    start = (page - 1) * page_size
    end = start + page_size
    page_products = products[start:end]

    rows: list[list[InlineKeyboardButton]] = []

    for p in page_products:
        pid = p["id"]
        qty = cart.get(pid, 0)
        check = "✅" if qty > 0 else "🟩"
        title = f"{check} {p['title']}, {p['weight_kg']} кг — {p['price']} руб."

        toggle_cb = f"cart:toggle:{pid}" if p["quantity"] > 0 else "noop"
        rows.append([InlineKeyboardButton(text=title, callback_data=toggle_cb)])

        if qty > 0:
            minus_cb = f"cart:sub:{pid}"
            plus_cb = f"cart:add:{pid}" if qty < p["quantity"] else "noop"
            rows.append([
                InlineKeyboardButton(text="➖", callback_data=minus_cb),
                InlineKeyboardButton(
                    text=f"{qty} шт (доступно {p['quantity']})",
                    callback_data="noop"
                ),
                InlineKeyboardButton(text="➕", callback_data=plus_cb),
            ])

    if total_pages > 1:
        prev_page = page - 1 if page > 1 else 1
        next_page = page + 1 if page < total_pages else total_pages
        rows.append([
            InlineKeyboardButton(text="«", callback_data="cart:page:1" if page > 1 else "noop"),
            InlineKeyboardButton(text="‹", callback_data=f"cart:page:{prev_page}" if page > 1 else "noop"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="›", callback_data=f"cart:page:{next_page}" if page < total_pages else "noop"),
            InlineKeyboardButton(text="»", callback_data=f"cart:page:{total_pages}" if page < total_pages else "noop"),
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
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="cart:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_create_order(bonuses: int,
                         used_bonus: int,
                         total_sum: float,
                         has_comment: bool)-> InlineKeyboardMarkup:
    """
    Создает клавиатуру для финального подтверждения заказа.
    :param bonuses: Всего доступно бонусов у пользователя.
    :param used_bonus: Сколько бонусов уже применено к заказу.
    :param total_sum: Полная стоимость заказа (товары + доставка).
    """
    builder = InlineKeyboardBuilder()

    comment_text = "📝 Изменить комментарий" if has_comment else "📝 Добавить комментарий"
    builder.button(text=comment_text, callback_data="order:add_comment")

    # Основные кнопки: "Подтвердить" и "Начать заново"
    builder.button(
        text="✅ Подтвердить и оформить",
        callback_data="confirm:ok"
    )
    builder.button(
        text="⬅️ Начать заново",
        callback_data="confirm:restart"
    )

    # Умная кнопка для бонусов:
    # Показываем ее, только если у пользователя есть бонусы И есть на что их тратить (сумма > 0)
    if bonuses > 0 and total_sum > 0:
        if used_bonus > 0:
            # Если бонусы уже применены, кнопка предлагает их отменить
            builder.button(
                text=f"Не списывать бонусы ({used_bonus} ₽)",
                callback_data="bonus:skip"
            )
        else:
            # Если бонусы не применены, кнопка предлагает их списать
            builder.button(
                text=f"💸 Списать бонусы ({bonuses} ₽)",
                callback_data="bonus:use"
            )

    # Располагаем кнопки: 2 в первой строке, 1 (если есть) во второй.
    builder.adjust(1,2, 1)

    return builder.as_markup()


def get_profile_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить имя и фамилию", callback_data="profile:edit-name")],
        [InlineKeyboardButton(text="Изменить номер телефона", callback_data="profile:edit-phone")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back-main")],
    ])


def cancel_payment(amount_to_pay: int, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"💳 Оплатить {amount_to_pay} RUB",
                pay=True
            ),
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=f"cancel_invoice:{order_id}"
            )
        ]
    ])


def back_to_delivery_choice_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура с одной кнопкой "Назад" для возврата к выбору способа доставки.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к выбору способа доставки", callback_data="cart:back")
    return builder.as_markup()


def confirm_geoposition_kb() -> InlineKeyboardMarkup:
    """
    Клавиатура для подтверждения правильности найденной геоточки.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, все верно", callback_data="geo:confirm")
    builder.button(text="⬅️ Назад", callback_data="cart:back")
    builder.adjust(2, 1)
    return builder.as_markup()
