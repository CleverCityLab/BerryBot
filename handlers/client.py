from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery

import keyboards.client
from database.managers.buyer_info_manager import BuyerInfoManager
from database.managers.buyer_order_manager import BuyerOrderManager
from database.managers.product_position_manager import ProductPositionManager
from database.managers.user_info_manager import UserInfoManager
from keyboards.client import (
    get_main_inline_keyboard,
    get_orders_inline_keyboard,
    get_orders_list_kb,
    get_order_detail_kb,
    get_cancel_confirm_kb,
    get_all_products,
    choice_of_delivery,
    delivery_address_select,
    confirm_create_order, get_profile_inline_keyboard
)
from utils.config import PAYMENT_TOKEN
from utils.constants import status_map, delivery_map
from utils.logger import get_logger
from utils.phone import normalize_phone
from utils.secrets import get_admin_ids

MIN_PAYMENT_AMOUNT = 60

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


class Registration(StatesGroup):
    full_name = State()
    phone = State()


class CreateOrder(StatesGroup):
    choose_products = State()
    choose_delivery = State()
    enter_address = State()
    confirm = State()
    waiting_payment = State()


class ProfileEdit(StatesGroup):
    full_name = State()
    phone = State()


def register_client(dp):
    dp.include_router(client_router)


@client_router.message(CommandStart())
async def client_start(message: Message, state: FSMContext, user_info_manager: UserInfoManager,
                       buyer_info_manager: BuyerInfoManager):
    log.info(f"[Bot.Client] Новый старт пользователя {message.from_user.id}")
    user_id = await user_info_manager.add_user(message.from_user.id)

    is_admin = message.from_user.id in get_admin_ids()
    if not is_admin:
        is_registered = await buyer_info_manager.is_registered(user_id)
        if is_registered:
            bonuses = await buyer_info_manager.get_user_bonuses_by_id(user_id)
            await message.answer(
                text="Выбери действие: \n"
                     f"Накоплено бонусов: `{bonuses if bonuses else 0}` руб.",
                parse_mode="Markdown",
                reply_markup=get_main_inline_keyboard(is_admin)
            )
            return
    else:
        await message.answer(
            text="Выбери действие: \n",
            reply_markup=get_main_inline_keyboard(is_admin)
        )
        return

    await message.answer(
        "Приветствуем Вас, новый покупатель! Давайте знакомиться.\n"
        "Введите *Ваше имя и фамилию*:",
        parse_mode="Markdown",
    )
    await state.set_state(Registration.full_name)


@client_router.message(Registration.full_name)
async def reg_get_fullname(message: Message, state: FSMContext) -> None:
    full_name: str = message.text.strip()

    log.info(f"[Bot.Client] Пользователь {message.from_user.id} вводит имя {full_name}")

    if len(full_name.split()) < 2:
        await message.answer("Пожалуйста, укажите *имя и фамилию* через пробел")
        return

    await state.update_data(full_name=full_name)
    await message.answer(
        "Введите *номер телефона* в формате `+77771234567` или `87771234567`:",
        parse_mode="Markdown",
    )
    await state.set_state(Registration.phone)


@client_router.message(Registration.phone)
async def reg_get_phone(
        message: Message,
        state: FSMContext,
        buyer_info_manager,
) -> None:
    phone_e164 = normalize_phone(message.text)

    log.info(f"[Bot.Client] Пользователь {message.from_user.id} вводит имя {phone_e164}")

    if phone_e164 is None:
        await message.answer(
            "Телефон выглядит некорректно. "
            "Укажите его, пожалуйста, ещё раз (пример: +77771234567):"
        )
        return

    data = await state.get_data()
    full_name: str = data["full_name"]
    tg_user_id = message.from_user.id

    await buyer_info_manager.create_buyer_info(
        tg_user_id=tg_user_id,
        name_surname=full_name,
        tel_num=phone_e164,
        tg_username=message.from_user.username,
    )

    await message.answer(
        "Спасибо, регистрация завершена! 🙌\nВыбери дальнейшее действие:",
        reply_markup=get_main_inline_keyboard(is_admin=False),
    )
    log.info(f"[Bot.Client] Пользователь {message.from_user.id} успешно зарегистрировался!")
    await state.clear()


@client_router.callback_query(F.data == "my-orders")
async def cb_my_orders(call: CallbackQuery, buyer_order_manager) -> None:
    await call.answer()
    tg_user_id = call.from_user.id
    log.info(f"[Bot.Client] Пользователь {tg_user_id} просматривает свои заказы")

    active_cnt = await buyer_order_manager.count_active_orders_by_tg(tg_user_id)
    total_cnt = await buyer_order_manager.count_total_orders_by_tg(tg_user_id)

    await call.message.edit_text(
        f"Кол-во ожидаемых заказов: `{active_cnt}` \nОбщее кол-во заказов: `{total_cnt}`",
        reply_markup=get_orders_inline_keyboard(),
        parse_mode="Markdown"
    )


@client_router.callback_query(F.data == "back-main")
async def cb_back_main(call: CallbackQuery, buyer_info_manager):
    await call.answer()
    is_admin = call.from_user.id in get_admin_ids()
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)
    try:
        await call.message.edit_text(
            text="Выбери действие: \n"
                 f"Накоплено бонусов: `{bonuses if bonuses else 0}` руб.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(is_admin),
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data == "orders-active")
async def show_active_list(call: CallbackQuery, buyer_order_manager):
    await call.answer()
    tg = call.from_user.id
    orders = await buyer_order_manager.list_orders(tg_user_id=tg, finished=False)
    cnt = len(orders)
    text = f"Кол-во ожидаемых заказов: `{cnt}`"

    try:
        await call.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=get_orders_list_kb(orders, finished=False)
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data == "orders-finished")
async def show_finished_list(call: CallbackQuery, buyer_order_manager):
    await call.answer()
    tg = call.from_user.id
    orders = await buyer_order_manager.list_orders(tg_user_id=tg, finished=True)
    cnt = len(orders)
    text = f"Кол-во завершённых заказов: `{cnt}`"

    try:
        await call.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=get_orders_list_kb(orders, finished=True)
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("order:"))
async def order_detail(call: CallbackQuery, buyer_order_manager):
    await call.answer()
    _, oid, kind = call.data.split(":")  # kind = act | fin
    order = await buyer_order_manager.get_order(call.from_user.id, int(oid))
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    items = await buyer_order_manager.list_items_by_order_id(order.id)
    if items:
        lines = [
            f"• {it.title} ×{it.qty} — `{it.price * it.qty}`₽"
            for it in items
        ]
        items_text = "\n".join(lines)
    else:
        items_text = "_пусто_"

    total = await buyer_order_manager.order_total_sum_by_order_id(order.id)

    status_txt = status_map[order.status.value]
    delivery_txt = delivery_map[order.delivery_way.value]

    text = (
        f"*Заказ №{order.id}*\n\n"
        f"*Товары:*\n{items_text}\n\n"
        f"*Итого:* `{total} ₽`\n"
        f"*Способ получения:* {delivery_txt}\n"
        f"*Статус:* {status_txt}\n"
        f"*Дата оформления:* {order.registration_date:%d.%m.%Y}"
    )
    if order.delivery_date:
        text += f"\n*Плановая дата получения:* {order.delivery_date:%d.%m.%Y}"

    try:
        await call.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_order_detail_kb(order),
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("cancel-no:"))
async def cancel_no(call: CallbackQuery, buyer_order_manager):
    _, order_id, suffix = call.data.split(":")
    order = await buyer_order_manager.get_order(call.from_user.id, int(order_id))
    if not order:
        await call.answer("Заказ уже не найден", show_alert=True)
        return

    items = await buyer_order_manager.list_items_by_order_id(order.id)
    if items:
        lines = [
            f"• {it.title} ×{it.qty} — `{it.price * it.qty}`₽"
            for it in items
        ]
        items_text = "\n".join(lines)
    else:
        items_text = "_пусто_"

    total = await buyer_order_manager.order_total_sum_by_order_id(order.id)

    status_txt = status_map[order.status.value]
    delivery_txt = delivery_map[order.delivery_way.value]

    text = (
        f"*Заказ №{order.id}*\n\n"
        f"*Товары:*\n{items_text}\n\n"
        f"*Итого:* `{total} ₽`\n"
        f"*Способ получения:* {delivery_txt}\n"
        f"*Статус:* {status_txt}\n"
        f"*Дата оформления:* {order.registration_date:%d.%m.%Y}"
    )
    if order.delivery_date:
        text += f"\n*Плановая дата получения:* {order.delivery_date:%d.%m.%Y}"

    try:
        await call.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_order_detail_kb(order),
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("order-cancel:"))
async def order_cancel_init(call: CallbackQuery):
    _, order_id, suffix = call.data.split(":")
    await call.answer()
    try:
        await call.message.edit_text(
            "Вы уверены, что хотите отменить заказ?",
            reply_markup=get_cancel_confirm_kb(int(order_id), suffix),
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("cancel-yes:"))
async def order_cancel_yes(call: CallbackQuery, buyer_order_manager):
    order_id = int(call.data.split(":")[1])
    await buyer_order_manager.cancel_order(order_id)

    await call.answer("Ваш заказ успешно отменён!", show_alert=True)

    orders = await buyer_order_manager.list_orders(
        tg_user_id=call.from_user.id, finished=False
    )
    header = f"Кол-во ожидаемых заказов: `{len(orders)}`"

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_orders_list_kb(orders, finished=False)
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("back-to-list:"))
async def back_to_list(call: CallbackQuery, buyer_order_manager):
    await call.answer()
    suffix = call.data.split(":")[1]
    finished = suffix == "fin"

    orders = await buyer_order_manager.list_orders(
        tg_user_id=call.from_user.id,
        finished=finished,
    )
    cnt = len(orders)
    header = (
        f"Кол-во ожидаемых заказов: `{cnt}`"
        if not finished else
        f"Кол-во завершённых заказов: `{cnt}`"
    )

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_orders_list_kb(orders, finished)
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("back-orders-menu:"))
async def back_orders_menu(call: CallbackQuery, buyer_order_manager):
    await call.answer()

    tg_id = call.from_user.id
    active_cnt = await buyer_order_manager.count_active_orders_by_tg(tg_id)
    total_cnt = await buyer_order_manager.count_total_orders_by_tg(tg_id)

    header = (
        f"Кол-во ожидаемых заказов: `{active_cnt}`\n"
        f"Общее кол-во заказов: `{total_cnt}`"
    )

    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_orders_inline_keyboard(),
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


def _text_cart_preview(items: list[dict], total: int, delivery_way: str, address: str | None,
                       used_bonus: int = 0) -> str:
    lines = ["*Вы выбрали:*"]
    for it in items:
        lines.append(f"• {it['title']} ×{it['qty']} — {it['price'] * it['qty']} ₽")
    lines.append(f"\nБонусов списано: `{used_bonus}`")
    lines.append(f"К оплате: `{total - used_bonus} ₽`")
    lines.append(f"Способ получения: *{'Доставка' if delivery_way == 'delivery' else 'Самовывоз'}*")
    if delivery_way == "delivery":
        lines.append(f"Адрес: {address or '—'}")
    return "\n".join(lines)


@client_router.callback_query(F.data == "create-order")
async def start_create(call: CallbackQuery, state: FSMContext, product_position_manager):
    await call.answer()
    await state.update_data(cart={})

    products = await product_position_manager.list_not_empty_order_positions()  # [{id,title,price,quantity}, ...]
    await state.set_state(CreateOrder.choose_products)
    await call.message.edit_text(
        "Выберите нужные позиции:",
        reply_markup=get_all_products(products, cart={})
    )


@client_router.callback_query(CreateOrder.choose_delivery, F.data == "cart:back")
async def back_from_delivery_to_cart(call: CallbackQuery, state: FSMContext, product_position_manager):
    data = await state.get_data()
    cart: dict[int, int] = data.get("cart", {})
    products = await product_position_manager.list_not_empty_order_positions()

    await state.set_state(CreateOrder.choose_products)
    await call.message.edit_text(
        "Выберите нужные позиции:",
        reply_markup=get_all_products(products, cart)
    )
    await call.answer()


@client_router.callback_query(CreateOrder.choose_products, F.data.startswith("cart:"))
async def cart_ops(call: CallbackQuery, state: FSMContext, product_position_manager):
    products = await product_position_manager.list_not_empty_order_positions()
    data = await state.get_data()
    cart: dict[int, int] = data.get("cart", {})

    action, *rest = call.data.split(":")[1:]
    if action == "done":
        if not cart:
            await call.answer(text="Корзина пуста", show_alert=True)
            return
        await state.update_data(cart=cart)
        await state.set_state(CreateOrder.choose_delivery)
        await call.message.edit_text("Способ получения:", reply_markup=choice_of_delivery())
        return

    pid = int(rest[0])
    stock_map = {p["id"]: p["quantity"] for p in products}
    qty = cart.get(pid, 0)

    if action == "toggle":
        cart.pop(pid, None) if qty > 0 else cart.__setitem__(pid, 1)
    elif action == "add":
        new_qty = min(qty + 1, stock_map.get(pid, 0))
        cart[pid] = new_qty
    elif action == "sub":
        new_qty = max(qty - 1, 0)
        if new_qty == 0:
            cart.pop(pid, None)
        else:
            cart[pid] = new_qty

    await state.update_data(cart=cart)
    await call.message.edit_text("Выберите нужные позиции:", reply_markup=get_all_products(products, cart))


@client_router.callback_query(CreateOrder.choose_delivery, F.data.startswith("del:"))
async def choose_delivery(call: CallbackQuery, state: FSMContext, buyer_info_manager, product_position_manager):
    await call.answer()
    arg = call.data.split(":")[1]
    await state.update_data(delivery_way="pickup" if arg == "pickup" else "delivery")

    if arg == "pickup":
        await go_confirm(call, state, buyer_info_manager, product_position_manager)
    else:
        saved = await buyer_info_manager.get_address_by_tg(call.from_user.id)
        await call.message.edit_text("Введите адрес или выберите сохранённый:",
                                     reply_markup=delivery_address_select(saved))


@client_router.callback_query(F.data == "addr:back")
async def back_from_address_to_delivery(call: CallbackQuery, state: FSMContext):
    await state.set_state(CreateOrder.choose_delivery)
    await call.message.edit_text("Способ получения:", reply_markup=choice_of_delivery())
    await call.answer()


@client_router.callback_query(CreateOrder.choose_delivery, F.data.startswith("addr:"))
async def address_flow(call: CallbackQuery, state: FSMContext, buyer_info_manager, product_position_manager):
    await call.answer()
    arg = call.data.split(":")[1]
    if arg == "use_saved":
        saved = await buyer_info_manager.get_address_by_tg(call.from_user.id)
        await state.update_data(address=saved or "")
        await go_confirm(call, state, buyer_info_manager, product_position_manager)
    elif arg == "enter":
        await call.message.edit_text("Введите адрес одним сообщением:")
        await state.set_state(CreateOrder.enter_address)


@client_router.message(CreateOrder.enter_address)
async def address_entered(msg: Message, state: FSMContext, buyer_info_manager, product_position_manager):
    addr = msg.text.strip()
    await state.update_data(address=addr)

    await buyer_info_manager.update_address_by_tg(msg.from_user.id, addr)
    await msg.answer("Адрес сохранён ✔️")
    await go_confirm(msg, state, buyer_info_manager, product_position_manager)


async def go_confirm(target: Message | CallbackQuery, state: FSMContext, buyer_info_manager, product_position_manager):
    data = await state.get_data()
    cart: dict[int, int] = data["cart"]
    delivery_way: str = data.get("delivery_way", "pickup")
    address: str | None = data.get("address")

    items = []
    total = 0

    products = await product_position_manager.get_order_position_by_ids(list(cart.keys()))
    pmap = {p["id"]: p for p in products}
    for pid, q in cart.items():
        p = pmap[pid]
        items.append({"title": p["title"], "price": p["price"], "qty": q})
        total += p["price"] * q

    # бонусы
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(
        target.from_user.id if isinstance(target, CallbackQuery) else target.from_user.id
    )

    used_bonus = data.get("used_bonus", 0)
    await state.update_data(total=total, bonuses=bonuses, used_bonus=used_bonus)

    text = _text_cart_preview(items, total, delivery_way, address, used_bonus)
    kb = confirm_create_order(bonuses, used_bonus)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except TelegramBadRequest as e:
            log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
            await handle_telegram_error(e, call=target)
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)
    await state.set_state(CreateOrder.confirm)


@client_router.callback_query(CreateOrder.confirm, F.data.in_({"bonus:use", "bonus:skip"}))
async def confirm_bonus(call: CallbackQuery, state: FSMContext, buyer_info_manager, product_position_manager):
    data = await state.get_data()
    if call.data.endswith("use"):
        used = min(data["bonuses"], data["total"])
        await state.update_data(used_bonus=used)
        await call.answer(f"Списываем {used} ₽ бонусов", show_alert=True)
    else:
        await call.answer()
        await state.update_data(used_bonus=0)
    await go_confirm(call, state, buyer_info_manager, product_position_manager)


@client_router.callback_query(CreateOrder.confirm, F.data == "confirm:restart")
async def confirm_restart(call: CallbackQuery, state: FSMContext, product_position_manager):
    await call.answer()
    await state.update_data(cart={})
    products = await product_position_manager.list_not_empty_order_positions()
    await state.set_state(CreateOrder.choose_products)
    await call.message.edit_text("Выберите нужные позиции:", reply_markup=get_all_products(products, cart={}))


@client_router.callback_query(CreateOrder.confirm, F.data == "confirm:ok")
async def confirm_ok(
        call: CallbackQuery,
        state: FSMContext,
        # Добавляем правильные type hint'ы для всех менеджеров
        buyer_order_manager: BuyerOrderManager,
        product_position_manager: ProductPositionManager,
        buyer_info_manager: BuyerInfoManager  # <-- Добавлен недостающий аргумент
):
    await call.answer()
    data = await state.get_data()
    cart: dict[int, int] = data["cart"]
    delivery_way: str = data.get("delivery_way", "pickup")
    address: str | None = data.get("address")
    used_bonus: int = data.get("used_bonus", 0)
    total: int = data.get("total", 0)

    # 1. Создаем заказ в базе
    order_id, err = await buyer_order_manager.create_order(
        tg_user_id=call.from_user.id,
        items=cart, delivery_way=delivery_way, address=address, used_bonus=used_bonus
    )

    if not order_id:
        await call.message.answer(err or "Не удалось создать заказ. Попробуйте снова.")
        return

    # 2. Рассчитываем сумму к оплате
    amount_to_pay = total - used_bonus

    # 3. Проверяем сумму и решаем, что делать
    if amount_to_pay >= MIN_PAYMENT_AMOUNT:
        # --- СЛУЧАЙ 1: Сумма достаточна для онлайн-оплаты ---
        try:
            log.info(f"Выставление счета на сумму {amount_to_pay} для заказа #{order_id}")
            await call.message.delete()

            await call.bot.send_invoice(
                chat_id=call.from_user.id,
                title=f"Оплата заказа №{order_id}",
                description="Оплата товаров из корзины",
                payload=f"order_payment:{order_id}",
                provider_token=PAYMENT_TOKEN,
                currency="RUB",
                prices=[LabeledPrice(label=f"Заказ №{order_id}", amount=int(amount_to_pay * 100))],
                reply_markup=keyboards.client.cancel_payment(amount_to_pay, order_id)
            )
            await state.set_state(CreateOrder.waiting_payment)

        except TelegramBadRequest as e:
            log.error(f"Ошибка при выставлении счета для заказа #{order_id}: {e}")
            await call.message.answer(
                "❗️ Произошла ошибка при создании счета на оплату. "
                "Ваш заказ был автоматически отменен. Пожалуйста, попробуйте снова."
            )
            await buyer_order_manager.cancel_order(order_id)
            await state.clear()

            is_admin = call.from_user.id in get_admin_ids()
            bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)
            await call.message.answer(
                text="Выбери действие: \n" f"Накоплено бонусов: `{bonuses or 0}` руб.",
                parse_mode="Markdown",
                reply_markup=get_main_inline_keyboard(is_admin)
            )


    elif amount_to_pay > 0:

        # --- СЛУЧАЙ 2: Сумма > 0, но < минимальной ---

        log.info(f"Сумма {amount_to_pay} для заказа #{order_id} слишком мала.")

        # 1. Отменяем заказ в базе данных, возвращая товары и бонусы

        await buyer_order_manager.cancel_order(order_id)

        # 2. Очищаем состояние FSM

        await state.clear()

        # 3. Сообщение с причиной
        await call.message.answer(text=f"Заказ отменен: сумма {amount_to_pay} руб. слишком мала для онлайн-оплаты.")
        # 4. Получаем данные для главного меню
        is_admin = call.from_user.id in get_admin_ids()
        bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)
        # 5. Редактируем сообщение, превращая его в главное меню
        await call.message.edit_text(
            text="Выбери действие: \n"
                 f"Накоплено бонусов: `{bonuses if bonuses else 0}` руб.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(is_admin)
        )

    else:
        # --- СЛУЧАЙ 3: Заказ полностью оплачен бонусами ---
        log.info(f"Заказ #{order_id} полностью оплачен бонусами.")
        await buyer_order_manager.mark_order_as_paid_by_bonus(order_id)
        await state.clear()
        await call.message.edit_text("✅ Заказ успешно оформлен и оплачен бонусами. Мы скоро свяжемся с вами.")


# Обработчик PreCheckoutQuery
@client_router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, buyer_order_manager):
    # Здесь можно добавить дополнительную проверку (например, наличие товара)
    order_id = int(pre_checkout_query.invoice_payload.split(":")[1])
    log.info(f"Получен pre-checkout запрос для заказа #{order_id}")

    # Подтверждаем, что готовы принять платеж
    await pre_checkout_query.answer(ok=True)
    log.info(f"Ответили ok=True на pre-checkout для заказа #{order_id}")


# Обработчик успешной оплаты
@client_router.message(F.successful_payment, CreateOrder.waiting_payment)
async def successful_payment_handler(message: Message, state: FSMContext, buyer_order_manager):
    payment_info = message.successful_payment
    order_id = int(payment_info.invoice_payload.split(":")[1])

    log.info(f"Оплата за заказ #{order_id} на сумму {payment_info.total_amount / 100} "
             f"{payment_info.currency} прошла успешно!")

    # Обновляем статус заказа в базе данных на "оплачен"
    # Вам нужно будет создать этот метод в вашем `buyer_order_manager`
    await buyer_order_manager.mark_order_as_paid(order_id, payment_info)

    await message.answer(
        "Оплата прошла успешно! ✅\n"
        f"Ваш заказ №{order_id} принят в работу. Мы скоро свяжемся с вами."
    )
    await state.clear()


@client_router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


async def _render_profile_text(tg_id: int, buyer_info_manager) -> str:
    rec = await buyer_info_manager.get_profile_by_tg(tg_id)
    if not rec:
        return "Данные профиля не найдены."
    name = rec["name_surname"]
    phone = rec["tel_num"]
    return (
        "*Изменить мои данные*\n\n"
        f"*Имя и фамилия:* {name}\n"
        f"*Номер телефона:* {phone}\n"
    )


async def show_profile_menu(target: Message | CallbackQuery, buyer_info_manager):
    tg_id = target.from_user.id if isinstance(target, CallbackQuery) else target.from_user.id
    await buyer_info_manager.upsert_username_by_tg(tg_id, target.from_user.username)
    text = await _render_profile_text(tg_id, buyer_info_manager)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_inline_keyboard())
        await target.answer()
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=get_profile_inline_keyboard())


@client_router.callback_query(F.data == "change-profile")
async def cb_open_profile(call: CallbackQuery, buyer_info_manager):
    await show_profile_menu(call, buyer_info_manager)


@client_router.callback_query(F.data == "profile:edit-name")
async def cb_edit_name(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEdit.full_name)
    await call.message.edit_text(
        "Введите *Ваши имя и фамилию* (через пробел):",
        parse_mode="Markdown"
    )
    await call.answer()


@client_router.message(ProfileEdit.full_name)
async def msg_set_name(message: Message, state: FSMContext, buyer_info_manager):
    full_name = " ".join(message.text.split()).strip()
    if len(full_name.split()) < 2:
        await message.answer("Пожалуйста, укажите *имя и фамилию* через пробел.", parse_mode="Markdown")
        return
    await buyer_info_manager.update_full_name_by_tg(message.from_user.id, full_name)
    await state.clear()
    await message.answer("Имя и фамилия *успешно изменены* ✅", parse_mode="Markdown")
    await show_profile_menu(message, buyer_info_manager)


@client_router.callback_query(F.data == "profile:edit-phone")
async def cb_edit_phone(call: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileEdit.phone)
    await call.message.edit_text(
        "Введите *Ваш номер телефона* в формате `+77771234567`:",
        parse_mode="Markdown"
    )
    await call.answer()


@client_router.message(ProfileEdit.phone)
async def msg_set_phone(message: Message, state: FSMContext, buyer_info_manager):
    phone_e164 = normalize_phone(message.text)
    if phone_e164 is None:
        await message.answer("Телефон выглядит некорректно. Повторите ввод в формате `+77771234567`.",
                             parse_mode="Markdown")
        return
    await buyer_info_manager.update_phone_by_tg(message.from_user.id, phone_e164)
    await state.clear()
    await message.answer("Номер телефона *успешно изменён* ✅", parse_mode="Markdown")
    await show_profile_menu(message, buyer_info_manager)


@client_router.callback_query(F.data.startswith("cancel_invoice:"))
async def cancel_payment_invoice(call: CallbackQuery, state: FSMContext, buyer_order_manager, buyer_info_manager):
    """
    Обрабатывает отмену заказа на этапе выставленного счета.
    Редактирует сообщение, превращая его в главное меню.
    """
    order_id = int(call.data.split(":")[1])

    # Отменяем заказ в базе данных (возвращаем товары и бонусы)
    await buyer_order_manager.cancel_order(order_id)

    await call.answer("Заказ отменён", show_alert=True)

    # Очищаем состояние FSM
    await state.clear()

    try:
        # 1. Удаляем сообщение со счетом, которое нельзя редактировать
        await call.message.delete()
    except TelegramBadRequest as e:
        # Игнорируем ошибку, если сообщение уже было удалено (например, при двойном клике)
        log.warning(f"Не удалось удалить сообщение при отмене счета: {e}")

        # 2. Отправляем абсолютно новое сообщение с главным меню
    is_admin = call.from_user.id in get_admin_ids()
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)

    await call.message.answer(
        text="Выбери действие: \n"
             f"Накоплено бонусов: `{bonuses if bonuses else 0}` руб.",
        parse_mode="Markdown",
        reply_markup=get_main_inline_keyboard(is_admin)
    )
