# handlers/order_processing.py

from contextlib import suppress
from typing import Union

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton

# Импорты ваших модулей
from api.yandex_delivery import YandexDeliveryClient, geocode_address
from database.managers.buyer_info_manager import BuyerInfoManager
from database.managers.buyer_order_manager import BuyerOrderManager
from database.managers.product_position_manager import ProductPositionManager
from database.managers.warehouse_manager import WarehouseManager
from handlers.client import client_router
from keyboards.client import (
    get_all_products, choice_of_delivery, delivery_address_select,
    confirm_create_order, confirm_geoposition_kb, get_main_inline_keyboard
)
from utils.config import PAYMENT_TOKEN
from utils.logger import get_logger
from utils.notifications import notify_admins, format_order_for_admin
from utils.secrets import get_admin_ids

# --- Константы и FSM ---
MIN_PAYMENT_AMOUNT = 60.00
log = get_logger("[Bot.OrderProcessing]")
order_router = Router()


class CreateOrder(StatesGroup):
    choose_products = State()
    choose_delivery = State()
    enter_address = State()
    confirm_geoposition = State()
    enter_porch = State()
    enter_floor = State()
    enter_apartment = State()
    confirm_order = State()
    waiting_payment = State()


# =======================================================================================
# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ХЕНДЛЕРЫ ============================
# =======================================================================================

def _text_order_preview(
        items: list[dict], total_goods: int, delivery_way: str,
        address: Union[str, None] = None, delivery_cost: float = 0.0, used_bonus: int = 0
) -> str:
    """Формирует текст для финального подтверждения заказа."""
    lines = ["*Ваш заказ:*"]
    for it in items:
        lines.append(f"• {it['title']} ×{it['qty']} — {it['price'] * it['qty']} ₽")

    lines.append(f"\n_Сумма по товарам: {total_goods} ₽_")

    if delivery_way == "delivery":
        lines.append(f"Доставка по адресу: _{address}_")
        lines.append(f"Стоимость доставки: *{delivery_cost:.2f} ₽*")

    final_total = total_goods + delivery_cost
    if used_bonus > 0:
        lines.append(f"Бонусов списано: `- {used_bonus}` ₽")

    lines.append(f"\n*Итого к оплате: {max(0.0, final_total - used_bonus):.2f} ₽*")
    return "\n".join(lines)


async def go_confirm(target: Message | CallbackQuery, state: FSMContext, buyer_info_manager: BuyerInfoManager,
                     product_position_manager: ProductPositionManager):
    data = await state.get_data()
    cart = data.get("cart", {})
    delivery_way = data.get("delivery_way")
    address = data.get("address")
    delivery_cost = data.get("delivery_cost", 0.0) if delivery_way == "delivery" else 0.0

    products = await product_position_manager.get_order_position_by_ids(list(cart.keys()))
    items = [{"title": p["title"], "price": p["price"], "qty": cart.get(p['id'], 0)} for p in products]
    total_goods = sum(it['price'] * it['qty'] for it in items)

    user_id = target.from_user.id
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(user_id)
    await state.update_data(total_goods=total_goods, bonuses=bonuses, items_preview=items)

    # Сначала показываем предпросмотр без списания бонусов
    text = _text_order_preview(items, total_goods, delivery_way, address, delivery_cost, used_bonus=0)
    full_price = total_goods + delivery_cost
    kb = confirm_create_order(bonuses, used_bonus=0, total_sum=full_price)

    message = target if isinstance(target, Message) else target.message
    # Удаляем предыдущее сообщение и отправляем новое, чтобы избежать путаницы
    if isinstance(target, CallbackQuery):
        await target.message.delete()
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await state.set_state(CreateOrder.confirm_order)


async def create_yandex_delivery_claim(
        bot: Bot, order_id: int, user_id: int,
        buyer_order_manager: BuyerOrderManager,
        buyer_info_manager: BuyerInfoManager,
        warehouse_manager: WarehouseManager,
        yandex_delivery_client: YandexDeliveryClient
):
    """
    Вспомогательная функция для создания заявки в Яндекс.Доставке.
    """
    await bot.send_message(user_id, "Создаем заявку на экспресс-доставку...")

    # 1. Получаем все необходимые данные
    order = await buyer_order_manager.get_order_by_id(order_id)
    warehouse = await warehouse_manager.get_default_warehouse()
    buyer_profile = await buyer_info_manager.get_profile_by_tg(user_id)

    if not (order and warehouse and buyer_profile):
        await notify_admins(bot, f"Не удалось собрать данные (заказ/склад/профиль) для заказа #{order_id}")
        await bot.send_message(user_id, "❗️Произошла ошибка при создании доставки. Мы уже занимаемся этим.")
        return

    order_items_from_db = await buyer_order_manager.list_items_by_order_id(order_id)
    if not order_items_from_db:
        await notify_admins(bot, f"Не найдены товары в заказе #{order_id} для создания заявки в Яндексе.")
        await bot.send_message(user_id, "❗️Произошла ошибка: не найдены товары в вашем заказе.")
        return

    # 2. Собираем items строго по API
    items_for_api = [
        {
            "quantity": int(item.qty),
            "pickup_point": 1,
            "dropoff_point": 2,
            "title": item.title,
            "weight": float(item.weight_kg),
            "size": {
                "length": float(item.length_m),
                "width": float(item.width_m),
                "height": float(item.height_m),
            }
        }
        for item in order_items_from_db
    ]

    # 3. Вызываем API
    claim_id = await yandex_delivery_client.create_claim(
        items=items_for_api,
        client_address=order.delivery_address,  # Передаем адрес как строку
        warehouse_info=warehouse,  # Передаем словарь склада
        buyer_info=dict(buyer_profile)  # Передаем словарь профиля
    )

    if claim_id:
        is_accepted = await yandex_delivery_client.accept_claim(claim_id)
        if is_accepted:
            await buyer_order_manager.save_claim_id(order_id, claim_id)
            await bot.send_message(user_id, "Заявка на доставку создана! Идет поиск курьера.")
        else:
            await notify_admins(bot, f"Не удалось подтвердить заявку в Яндексе для заказа #{order_id}")
            await bot.send_message(user_id, "❗️Ошибка при подтверждении доставки. Мы уже занимаемся этим.")
    else:
        await notify_admins(bot, f"Не удалось создать заявку в Яндексе для заказа #{order_id}")
        await bot.send_message(user_id, "❗️Ошибка при создании доставки. Мы уже занимаемся этим.")


# =======================================================================================
# ======================== ОСНОВНАЯ ЦЕПОЧКА FSM ДЛЯ ЗАКАЗА ==============================
# =======================================================================================

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
async def choose_delivery(call: CallbackQuery, state: FSMContext, buyer_info_manager: BuyerInfoManager,
                          product_position_manager: ProductPositionManager):
    delivery_way = "delivery" if call.data.split(":")[1] == "delivery" else "pickup"
    await state.update_data(delivery_way=delivery_way)

    if delivery_way == "pickup":
        await go_confirm(call, state, buyer_info_manager, product_position_manager)
    else:
        saved_address = await buyer_info_manager.get_address_by_tg(call.from_user.id)
        await call.message.edit_text("Укажите адрес доставки:", reply_markup=delivery_address_select(saved_address))
        await state.set_state(CreateOrder.enter_address)
    await call.answer()


# --- БЛОК ВВОДА И ВЕРИФИКАЦИИ АДРЕСА ---

# --- Шаг 3.1: Пользователь нажимает "Доставка" ---
@client_router.callback_query(CreateOrder.choose_delivery, F.data == "del:delivery")
async def start_address_entry(call: CallbackQuery, state: FSMContext, buyer_info_manager: BuyerInfoManager):
    """
    Запускает процесс ввода адреса.
    """
    await call.answer()
    saved_address = await buyer_info_manager.get_address_by_tg(call.from_user.id)

    await call.message.edit_text(
        "Введите основную часть адреса (Город, улица, дом):",
        reply_markup=delivery_address_select(saved_address)  # Клавиатура с "Использовать сохраненный"
    )
    await state.set_state(CreateOrder.enter_address)


# --- Шаг 3.2: Пользователь вводит адрес текстом ---
@client_router.message(CreateOrder.enter_address, F.text)
async def process_text_address(msg: Message, state: FSMContext, bot: Bot):
    address_text = msg.text.strip()
    await msg.answer("⏳ Ищу адрес на карте...")

    coords = await geocode_address(address_text)
    if not coords:
        await msg.answer("Не удалось найти такой адрес. Попробуйте ввести его подробнее или отправьте геоточку.")
        return

    lon, lat = coords
    await state.update_data(address=address_text, latitude=lat, longitude=lon)
    await state.set_state(CreateOrder.confirm_geoposition)

    await bot.send_location(chat_id=msg.chat.id, latitude=lat, longitude=lon)
    await msg.answer(
        "Я нашел адрес здесь. Все верно?",
        reply_markup=confirm_geoposition_kb()
    )


# --- Шаг 3.3: Пользователь отправляет геолокацию (на первом или втором шаге) ---
@client_router.message(CreateOrder.enter_address, F.location)
@client_router.message(CreateOrder.confirm_geoposition, F.location)
async def process_manual_location(msg: Message, state: FSMContext):
    await state.update_data(
        latitude=msg.location.latitude,
        longitude=msg.location.longitude,
        address=f"Геометка ({msg.location.latitude:.5f}, {msg.location.longitude:.5f})"
    )
    await state.set_state(CreateOrder.enter_porch)
    await msg.answer("Точка принята! Теперь введите **подъезд** (или отправьте прочерк `-`):")


# --- Шаг 3.4: Пользователь реагирует на карту ---
@client_router.callback_query(CreateOrder.confirm_geoposition, F.data.startswith("geo:"))
async def process_geoposition_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":")[1]

    # Удаляем предыдущие сообщения, чтобы не было мусора
    with suppress(TelegramBadRequest):
        await call.message.delete()
        await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id - 1)

    if action == "confirm":
        await state.set_state(CreateOrder.enter_porch)
        await call.message.answer("Отлично! Теперь введите **подъезд** (или отправьте прочерк `-`):")
        return

    if action == "manual":
        await call.message.answer("Хорошо, пожалуйста, отправьте мне геолокацию (Скрепка 📎 -> Геопозиция).")
        # Состояние остается confirm_geoposition, ждем локацию


# --- Шаг 3.5: Кнопка "Назад" с экрана подтверждения геопозиции ---
@client_router.callback_query(CreateOrder.confirm_geoposition, F.data == "cart:back")
async def back_from_geoconfirm_to_delivery_choice(call: CallbackQuery, state: FSMContext):
    await call.answer()
    with suppress(TelegramBadRequest):
        await call.message.delete()
        await call.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id - 1)

    await call.message.answer(
        "Как вы хотите получить заказ?",
        reply_markup=choice_of_delivery()
    )
    await state.set_state(CreateOrder.choose_delivery)


# --- БЛОК ВВОДА ДЕТАЛЕЙ АДРЕСА И РАСЧЕТА ---

# --- Шаг 3.6, 3.7, 3.8: Ввод деталей и финальный расчет ---
@client_router.message(CreateOrder.enter_porch, F.text)
async def process_porch(msg: Message, state: FSMContext):
    porch = msg.text.strip()
    await state.update_data(porch=porch if porch != '-' else None)
    await state.set_state(CreateOrder.enter_floor)
    await msg.answer("Принято. Теперь введите **этаж** (или отправьте прочерк `-`):")


@client_router.message(CreateOrder.enter_floor, F.text)
async def process_floor(msg: Message, state: FSMContext):
    floor = msg.text.strip()
    await state.update_data(floor=floor if floor != '-' else None)
    await state.set_state(CreateOrder.enter_apartment)
    await msg.answer("И последний шаг: введите **номер квартиры/офиса** (или отправьте прочерк `-`):")


@client_router.message(CreateOrder.enter_apartment, F.text)
async def process_apartment_and_calculate(
        msg: Message, state: FSMContext, bot: Bot,
        buyer_info_manager: BuyerInfoManager,
        product_position_manager: ProductPositionManager,
        warehouse_manager: WarehouseManager,
        yandex_delivery_client: YandexDeliveryClient
):
    # apartment = msg.text.strip()
    # data = await state.get_data()
    """
    Финальный шаг ввода адреса. Собирает все данные, сохраняет их,
    рассчитывает стоимость доставки и переходит к подтверждению заказа.
    """
    apartment = msg.text.strip()
    await state.update_data(apartment=apartment if apartment != '-' else None)
    data = await state.get_data()

    # --- ШАГ 1: СОХРАНЯЕМ ВСЕ ДЕТАЛИ В БД ---
    main_address = data.get("address", "")
    await buyer_info_manager.upsert_address_details(
        tg_user_id=msg.from_user.id,
        full_address=main_address,
        porch=data.get('porch'),
        floor=data.get('floor'),
        apartment=apartment if apartment != '-' else None
    )

    await msg.answer("⏳ Адрес сохранен! Рассчитываем стоимость доставки...")

    # --- ШАГ 2: ИЗВЛЕКАЕМ ПОЛНЫЙ ПРОФИЛЬ ИЗ БД ---
    # Теперь buyer_profile содержит все, что мы только что сохранили
    buyer_profile = await buyer_info_manager.get_profile_by_tg(msg.from_user.id)
    if not buyer_profile:
        await msg.answer("Ошибка: не удалось получить ваш профиль.")
        log.error(
            f"Не удалось получить профиль пользователя {msg.from_user.id}"
            f" при расчете доставки в хендлере process_apartment_and_calculate")
        return

    # 2. Получаем данные о складе
    warehouse = await warehouse_manager.get_default_warehouse()
    if not warehouse:
        await notify_admins(bot,
                            f"‼️ Критическая ошибка: не найден склад. "
                            f"Пользователь {msg.from_user.id} не может оформить доставку.")
        await msg.answer("❗️Системная ошибка. Мы уже работаем над решением.")
        return

    # 3. Готовим `items` для API
    cart = data.get("cart", {})
    products = await product_position_manager.get_order_position_by_ids(list(cart.keys()))
    items_for_api = [
        {
            "quantity": cart.get(p['id'], 0),
            "size": {"length": p['length_m'], "width": p['width_m'], "height": p['height_m']},
            "weight": p['weight_kg']
        }
        for p in products if cart.get(p['id'], 0) > 0
    ]

    delivery_cost = await yandex_delivery_client.calculate_price(
        items=items_for_api,
        client_address=main_address,  # Основной адрес для геокодирования
        warehouse_info=warehouse,
        buyer_info=dict(buyer_profile)  # Передаем полный профиль со всеми деталями
    )

    if delivery_cost is None:  # ... (обработка ошибки расчета)
        return

        # --- ШАГ 4: ЗАВЕРШАЕМ ПРОЦЕСС ---
        # Собираем полный адрес для отображения
        details = []

        if buyer_profile.get('porch'):
            details.append(f"подъезд {buyer_profile['porch']}")
        if buyer_profile.get('floor'):
            details.append(f"этаж {buyer_profile['floor']}")
        if buyer_profile.get('apartment'):
            details.append(f"кв./офис {buyer_profile['apartment']}")
        full_address_for_display = f"{main_address}, {', '.join(details)}" if details else main_address

        await state.update_data(
            address=full_address_for_display,  # В state сохраняем красивую полную строку
            delivery_cost=delivery_cost
        )

        await msg.answer(f"Стоимость доставки: *{delivery_cost:.2f} руб.*", parse_mode="Markdown")
        await go_confirm(msg, state, buyer_info_manager, product_position_manager)
    # 7. Все успешно. Сохраняем стоимость и переходим к подтверждению.
    await state.update_data(delivery_cost=delivery_cost)
    await msg.answer(f"Стоимость доставки: *{delivery_cost:.2f} руб.*", parse_mode="Markdown")

    # Вызываем функцию, которая покажет финальный экран с кнопками "Оформить", "Бонусы" и т.д.
    await go_confirm(msg, state, buyer_info_manager, product_position_manager)


# --- БЛОК ФИНАЛЬНОГО ПОДТВЕРЖДЕНИЯ И ОПЛАТЫ ---

@client_router.callback_query(CreateOrder.confirm_order, F.data.in_({"bonus:use", "bonus:skip"}))
async def confirm_bonus(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()

    # --- Получаем все нужные данные из состояния ---
    bonuses = data.get("bonuses", 0)
    total_goods = data.get("total_goods", 0)
    delivery_cost = data.get("delivery_cost", 0.0)
    items_preview = data.get("items_preview", [])
    delivery_way = data.get("delivery_way")
    address = data.get("address")

    # Бонусами можно оплатить только стоимость товаров, не доставки.
    can_use_bonus = min(bonuses, total_goods)
    used_bonus = can_use_bonus if call.data.endswith("use") else 0

    # Сохраняем выбор пользователя в состояние
    await state.update_data(used_bonus=used_bonus)

    # Формируем обновленный текст предпросмотра
    text = _text_order_preview(items_preview, total_goods, delivery_way, address, delivery_cost, used_bonus)

    # Формируем обновленную клавиатуру
    full_price = total_goods + delivery_cost
    kb = confirm_create_order(bonuses, used_bonus, total_sum=full_price)

    # Редактируем сообщение с новыми данными
    await call.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)


@client_router.callback_query(CreateOrder.confirm_order, F.data == "confirm:restart")
async def confirm_restart(call: CallbackQuery, state: FSMContext, product_position_manager):
    await call.answer()
    await state.update_data(cart={})
    products = await product_position_manager.list_not_empty_order_positions()
    await state.set_state(CreateOrder.choose_products)
    await call.message.edit_text("Выберите нужные позиции:", reply_markup=get_all_products(products, cart={}))


@client_router.callback_query(CreateOrder.confirm_order, F.data == "confirm:ok")
async def confirm_ok(
        call: CallbackQuery,
        state: FSMContext,
        bot: Bot,
        buyer_order_manager: BuyerOrderManager,
        buyer_info_manager: BuyerInfoManager,
        warehouse_manager: WarehouseManager,
        yandex_delivery_client: YandexDeliveryClient
):
    await call.answer()
    data = await state.get_data()

    # --- Получаем все данные из состояния для финальной операции ---
    cart = data.get("cart", {})
    delivery_way = data.get("delivery_way")
    address = data.get("address")
    used_bonus = data.get("used_bonus", 0)
    total_goods = data.get("total_goods", 0)
    delivery_cost = data.get("delivery_cost", 0.0)

    # Рассчитываем итоговую сумму, которую нужно оплатить деньгами
    final_amount_to_pay = total_goods + delivery_cost - used_bonus

    # 1. Создаем заказ в БД со всеми данными
    order_id, err = await buyer_order_manager.create_order(
        tg_user_id=call.from_user.id,
        items=cart,
        delivery_way=delivery_way,
        address=address,
        used_bonus=used_bonus,
        delivery_cost=delivery_cost
    )
    if not order_id:
        await call.message.edit_text(err or "Не удалось создать заказ. Попробуйте снова.")
        await state.clear()
        return

    # 2. Решаем, что делать дальше, на основе суммы к оплате
    if final_amount_to_pay >= MIN_PAYMENT_AMOUNT:
        # --- СЛУЧАЙ 1: Сумма достаточна, отправляем на оплату ---
        try:
            await call.message.delete()  # Удаляем сообщение с предпросмотром

            payment_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"💳 Оплатить {final_amount_to_pay:.2f} RUB", pay=True),
                InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_invoice:{order_id}")
            ]])

            await bot.send_invoice(
                chat_id=call.from_user.id,
                title=f"Оплата заказа №{order_id}",
                description=f"Оплата товаров и доставки на сумму {final_amount_to_pay:.2f} руб.",
                payload=f"order_payment:{order_id}",
                provider_token=PAYMENT_TOKEN,
                currency="RUB",
                prices=[LabeledPrice(label=f"Заказ №{order_id}", amount=int(final_amount_to_pay * 100))],
                reply_markup=payment_kb
            )
            await state.set_state(CreateOrder.waiting_payment)
        except TelegramBadRequest as e:
            log.error(f"Ошибка при выставлении счета для заказа #{order_id}: {e}")
            await call.message.answer("❗️ Произошла ошибка при создании счета. Ваш заказ отменен.")
            await buyer_order_manager.cancel_order(order_id)
            await state.clear()

    elif final_amount_to_pay > 0:
        # --- СЛУЧАЙ 2: Сумма > 0, но < минимальной ---
        await call.answer("Заказ отменен: сумма к оплате слишком мала.", show_alert=True)
        await buyer_order_manager.cancel_order(order_id)

        is_admin = call.from_user.id in get_admin_ids()
        bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)
        await call.message.edit_text(
            text=f"❗️Сумма к оплате ({final_amount_to_pay:.2f} руб.)"
                 f" меньше минимальной ({MIN_PAYMENT_AMOUNT} руб.). Заказ отменен.\n\n"
                 "Выберите действие:\n"
                 f"Накоплено бонусов: `{bonuses or 0}` руб.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(is_admin)
        )
        await state.clear()

    else:
        # --- СЛУЧАЙ 3: Заказ полностью оплачен бонусами ---
        await buyer_order_manager.mark_order_as_paid_by_bonus(order_id)
        await call.message.edit_text("✅ Заказ успешно оплачен бонусами.")

        # Получаем объект BuyerOrders
        order_object = await buyer_order_manager.get_order_by_id(order_id)

        # Если это доставка, сразу создаем заявку в Яндексе
        order_data = await buyer_order_manager.get_order_by_id(order_id)
        if order_data:
            if delivery_way == 'delivery':
                await create_yandex_delivery_claim(bot, order_id, call.from_user.id, buyer_order_manager,
                                                   buyer_info_manager, warehouse_manager, yandex_delivery_client)
                # order_data = await buyer_order_manager.get_order_by_id(order_id)

            buyer_data = await buyer_info_manager.get_profile_by_tg(call.from_user.id)
            # items_data = [dict(item._asdict()) for item in await buyer_order_manager.list_items_by_order_id(order_id)]
            items_list = await buyer_order_manager.list_items_by_order_id(order_id)

            admin_text, admin_kb = format_order_for_admin(order_object, buyer_data, items_list)
            await notify_admins(bot, text=admin_text, reply_markup=admin_kb)
        # --- КОНЕЦ БЛОКА УВЕДОМЛЕНИЯ ---

        await state.clear()


# --- ОБРАБОТКА УСПЕШНОЙ ОПЛАТЫ ---

# Обработчик успешной оплаты
@client_router.message(F.successful_payment, CreateOrder.waiting_payment)
async def successful_payment_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
        buyer_order_manager: BuyerOrderManager,
        buyer_info_manager: BuyerInfoManager,
        warehouse_manager: WarehouseManager,
        yandex_delivery_client: YandexDeliveryClient
):
    order_id = int(message.successful_payment.invoice_payload.split(":")[1])

    # 1. Обновляем статус заказа в БД
    await buyer_order_manager.mark_order_as_paid(order_id, message.successful_payment)

    # 2. Отправляем короткое сообщение об успехе (без кнопок)
    await message.answer(f"✅ Оплата прошла! Ваш заказ №{order_id} принят в работу.")

    # 3. Создаем заявку в Яндексе, если это доставка
    order_object = await buyer_order_manager.get_order_by_id(order_id)
    if order_object and order_object.delivery_way.value == 'delivery':
        # Этот вызов отправит свои сообщения ("Создаем заявку...")
        await create_yandex_delivery_claim(
            bot, order_id, message.from_user.id,
            buyer_order_manager, buyer_info_manager,
            warehouse_manager, yandex_delivery_client
        )
        # Перезагружаем данные заказа, так как мог появиться yandex_claim_id
        order_object = await buyer_order_manager.get_order_by_id(order_id)

    # 4. Отправляем уведомление администратору
    if order_object:
        buyer_data = await buyer_info_manager.get_profile_by_tg(message.from_user.id)
        items_list = await buyer_order_manager.list_items_by_order_id(order_id)
        if buyer_data and items_list:
            admin_text, admin_kb = format_order_for_admin(order_object, buyer_data, items_list)
            await notify_admins(bot, text=admin_text, reply_markup=admin_kb)

    # 5. Очищаем состояние FSM
    await state.clear()

    # --- ФИНАЛЬНЫЙ ШАГ: "КИДАЕМ НА ГЛАВНОЕ МЕНЮ" ---
    # Получаем актуальные данные для меню
    is_admin = message.from_user.id in get_admin_ids()
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(message.from_user.id)

    # Отправляем новое, полноценное сообщение главного меню
    await message.answer(
        text="Выбери действие: \n"
             f"Накоплено бонусов: `{bonuses or 0}` руб.",
        parse_mode="Markdown",
        reply_markup=get_main_inline_keyboard(is_admin)
    )


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
