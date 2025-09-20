# handlers/order_processing.py
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Union, Tuple

import aiohttp
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

from handlers.client import order_detail as show_client_order_detail

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
    enter_comment = State()
    confirm_order = State()
    waiting_payment = State()


# =======================================================================================
# ======================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ХЕНДЛЕРЫ ============================
# =======================================================================================

def _text_order_preview(
        items: list[dict], total_goods: int, delivery_way: str,
        address: Union[str, None] = None, delivery_cost: float = 0.0, used_bonus: int = 0,
        comment: Union[str, None] = None
) -> str:
    """Формирует текст для финального подтверждения заказа."""
    lines = ["*Ваш заказ:*"]
    for it in items:
        lines.append(f"• {it['title']} ×{it['qty']} — {it['price'] * it['qty']} ₽")

    lines.append(f"\n_Сумма по товарам: {total_goods} ₽_")

    if delivery_way == "delivery":
        lines.append(f"Доставка по адресу: _{address}_")
        lines.append(f"Стоимость доставки: *{delivery_cost:.2f} ₽*")

    if comment:
        lines.append(f"\nКомментарий: _{comment}_")

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
    comment = data.get("comment")

    products = await product_position_manager.get_order_position_by_ids(list(cart.keys()))
    items = [{"title": p["title"], "price": p["price"], "qty": cart.get(p['id'], 0)} for p in products]
    total_goods = sum(it['price'] * it['qty'] for it in items)

    user_id = target.from_user.id
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(user_id)
    await state.update_data(total_goods=total_goods, bonuses=bonuses, items_preview=items)

    # Сначала показываем предпросмотр без списания бонусов
    text = _text_order_preview(items, total_goods, delivery_way, address, delivery_cost, used_bonus=0, comment=comment)
    full_price = total_goods + delivery_cost
    kb = confirm_create_order(bonuses, 0, full_price, has_comment=bool(comment))

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
        await notify_admins(bot, "Не удалось собрать "
                                 f"данные (заказ/склад/профиль) для заказа #{order_id}")
        await bot.send_message(user_id, "❗️Произошла ошибка при создании доставки. "
                                        "Мы уже занимаемся этим.")
        return

    order_items_from_db = await buyer_order_manager.list_items_by_order_id(order_id)
    if not order_items_from_db:
        await notify_admins(bot, f"Не найдены товары в заказе #{order_id} для создания заявки в Яндексе.")
        await bot.send_message(user_id, "❗️Произошла ошибка: не найдены товары в вашем заказе.")
        return

    # 2. Берем ЧИСТЫЙ адрес из ПРОФИЛЯ для геокодирования
    main_address_for_geocoding = buyer_profile.get("address")
    if not main_address_for_geocoding:
        log.error("Нет адреса для доставки")
        await bot.send_message(user_id, "❗️Произошла ошибка при получении Вашего адреса. "
                                        "Пожалуйста, повторите попытку заказа")
        return

    coords = await geocode_address(main_address_for_geocoding)
    if not coords:
        error_msg = (f"Не удалось геокодировать адрес '{main_address_for_geocoding}' "
                     f"для заказа #{order_id} при создании заявки.")
        log.error(error_msg)
        await notify_admins(bot, error_msg)
        await bot.send_message(user_id,
                               "❗️Произошла ошибка при определении координат вашего адреса. Мы уже занимаемся этим.")
        return
    client_lon, client_lat = coords

    client_info = {
        "name": buyer_profile['name_surname'],
        "phone": buyer_profile['tel_num'],
        "address": order.delivery_address,  # Основной адрес из заказа
        "porch": buyer_profile['porch'],  # Детали из профиля
        "floor": buyer_profile['floor'],
        "apartment": buyer_profile['apartment'],
        "latitude": client_lat,  # Свежие координаты
        "longitude": client_lon
    }

    # 2. Собираем items строго по API
    items_for_api = [
        {
            "cost_currency": "RUB",
            "cost_value": str(item.price),
            "quantity": item.qty,
            "title": item.title,
            "pickup_point": 1,
            "dropoff_point": 2,
            "weight": float(item.weight_kg),
            "size": {
                "length": float(item.length_m),
                "width": float(item.width_m),
                "height": float(item.height_m)
            }
        }
        for item in order_items_from_db
    ]

    # 3. Вызываем API
    claim_id = await yandex_delivery_client.create_claim(
        items=items_for_api,
        client_info=client_info,  # <-- Теперь это client_info
        warehouse_info=warehouse,
        order_id=order_id,  # <-- Теперь это order_id
        order_comment = order.comment
    )

    if claim_id:
        await asyncio.sleep(5)
        accepted_info = await yandex_delivery_client.accept_claim(claim_id)
        if accepted_info:  # <-- Проверяем, что ответ не None
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


# --- Шаг 1: Пользователь нажимает "Доставка" или "Самовывоз" ---
@client_router.callback_query(CreateOrder.choose_delivery, F.data.startswith("del:"))
async def handle_delivery_choice(call: CallbackQuery, state: FSMContext, buyer_info_manager: BuyerInfoManager,
                                 product_position_manager: ProductPositionManager):
    """
    Обрабатывает выбор способа доставки.
    """
    await call.answer()
    delivery_way = "delivery" if call.data.split(":")[1] == "delivery" else "pickup"
    await state.update_data(delivery_way=delivery_way)

    if delivery_way == "pickup":
        # Если самовывоз, сразу переходим к подтверждению
        await go_confirm(call, state, buyer_info_manager, product_position_manager)
    else:
        # Если доставка, запускаем процесс ввода адреса
        await call.message.edit_text(
            "Введите адрес доставки (город, улица, дом)"
        )
        await state.set_state(CreateOrder.enter_address)


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
        await msg.answer("Не удалось найти такой адрес. Попробуйте ввести его подробнее")
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
@client_router.message(CreateOrder.confirm_geoposition, F.location)
async def process_manual_location(msg: Message, state: FSMContext):
    await state.update_data(
        latitude=msg.location.latitude,
        longitude=msg.location.longitude,
    )
    await state.set_state(CreateOrder.enter_porch)
    await msg.answer("Точка принята! Теперь введите **подъезд** (или отправьте прочерк `-`):", parse_mode="Markdown")


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
        await call.message.answer("Отлично! Теперь введите **подъезд** (или отправьте прочерк `-`):",
                                  parse_mode="Markdown")
        return


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
    await msg.answer("Принято. Теперь введите **этаж** (или отправьте прочерк `-`):", parse_mode="Markdown")


@client_router.message(CreateOrder.enter_floor, F.text)
async def process_floor(msg: Message, state: FSMContext):
    floor = msg.text.strip()
    await state.update_data(floor=floor if floor != '-' else None)
    await state.set_state(CreateOrder.enter_apartment)
    await msg.answer("И последний шаг: введите **номер квартиры/офиса** (или отправьте прочерк `-`):",
                     parse_mode="Markdown")


@client_router.message(CreateOrder.enter_apartment, F.text)
async def process_apartment_and_calculate(
        msg: Message,
        state: FSMContext,
        bot: Bot,
        buyer_info_manager: BuyerInfoManager,
        product_position_manager: ProductPositionManager,
        warehouse_manager: WarehouseManager,
        yandex_delivery_client: YandexDeliveryClient
):
    """
    Финальный шаг ввода адреса. Собирает, сохраняет, рассчитывает
    и корректно обрабатывает все возможные ошибки.
    """
    apartment = msg.text.strip()
    await state.update_data(apartment=apartment if apartment != '-' else None)
    data = await state.get_data()
    main_address = data.get("address", "")

    # --- Общая функция для возврата в главное меню при ошибке ---
    async def return_to_main_menu(error_message: str):
        await msg.answer(error_message)
        await state.clear()

        is_admin = msg.from_user.id in get_admin_ids()
        bonuses = await buyer_info_manager.get_user_bonuses_by_tg(msg.from_user.id)

        await msg.answer(
            text="Выбери действие: \n"
                 f"Накоплено бонусов: `{bonuses or 0}` руб.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(is_admin)
        )

    # 1. Сохраняем все детали в БД
    await buyer_info_manager.upsert_address_details(
        tg_user_id=msg.from_user.id,
        full_address=main_address,
        porch=data.get('porch'),
        floor=data.get('floor'),
        apartment=data.get('apartment')
    )

    await msg.answer("⏳ Адрес сохранен! Рассчитываем стоимость доставки...")

    # 2. Проверяем наличие склада
    warehouse = await warehouse_manager.get_default_warehouse()
    if not warehouse:
        error_msg = ("‼️ Критическая ошибка: не найден склад. "
                     f"Пользователь {msg.from_user.id} не может оформить доставку.")
        log.error(error_msg)
        await notify_admins(bot, error_msg)
        await return_to_main_menu("❗️Произошла системная ошибка. Мы уже работаем над решением.")
        return

    # 3. Проверяем наличие профиля
    buyer_profile = await buyer_info_manager.get_profile_by_tg(msg.from_user.id)
    if not buyer_profile:
        log.error(f"Не найден профиль для {msg.from_user.id} на этапе расчета.")
        await return_to_main_menu("❗️Произошла системная ошибка: не найден ваш профиль.")
        return

    # 4. Готовим `items` для API
    cart = data.get("cart", {})
    products = await product_position_manager.get_order_position_by_ids(list(cart.keys()))
    items_for_api = [
        {"quantity": cart.get(p['id'], 0),
         "size": {"length": p['length_m'], "width": p['width_m'], "height": p['height_m']}, "weight": p['weight_kg']}
        for p in products if cart.get(p['id'], 0) > 0
    ]

    # 5. Вызываем API и обрабатываем возможный сбой
    try:
        delivery_cost = await yandex_delivery_client.calculate_price(
            items=items_for_api,
            client_address=main_address,
            warehouse_info=warehouse,
            buyer_info=dict(buyer_profile)
        )
    except Exception as e:
        log.exception(f"Непредвиденное исключение в yandex_delivery_client.calculate_price: {e}")
        delivery_cost = None  # Считаем, что расчет не удался

    if delivery_cost is None:
        # Эта ветка теперь ловит и ошибку API, и непредвиденное исключение
        await return_to_main_menu(
            "❗️Не удалось рассчитать доставку по вашему адресу."
            " Заказ отменен. Пожалуйста, попробуйте снова.")
        return

    # 6. Все успешно, завершаем процесс
    details = []
    if buyer_profile.get('porch'):
        details.append(f"подъезд {buyer_profile['porch']}")
    if buyer_profile.get('floor'):
        details.append(f"этаж {buyer_profile['floor']}")
    if buyer_profile.get('apartment'):
        details.append(f"кв./офис {buyer_profile['apartment']}")
    full_address_for_display = f"{main_address}, {', '.join(details)}" if details else main_address

    await state.update_data(
        address=full_address_for_display,
        delivery_cost=delivery_cost
    )

    await msg.answer(f"Стоимость доставки: *{delivery_cost:.2f} руб.*", parse_mode="Markdown")
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

@client_router.callback_query(CreateOrder.confirm_order, F.data == "order:add_comment")
async def start_add_comment(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите ваш комментарий к заказу (например, 'позвонить за час до доставки'):")
    await state.set_state(CreateOrder.enter_comment)
    await call.answer()

# Этот хендлер ловит сам текст комментария
@client_router.message(CreateOrder.enter_comment, F.text)
async def process_comment(
    msg: Message,
    state: FSMContext,
    buyer_info_manager: BuyerInfoManager,
    product_position_manager: ProductPositionManager
):
    await state.update_data(comment=msg.text.strip())
    await msg.answer("Комментарий добавлен.")
    # Возвращаем пользователя на экран подтверждения
    await go_confirm(msg, state, buyer_info_manager, product_position_manager)


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
    comment = data.get("comment")

    # Рассчитываем итоговую сумму, которую нужно оплатить деньгами
    final_amount_to_pay = total_goods + delivery_cost - used_bonus

    # 1. Создаем заказ в БД со всеми данными
    order_id, err = await buyer_order_manager.create_order(
        tg_user_id=call.from_user.id,
        items=cart,
        delivery_way=delivery_way,
        address=address,
        used_bonus=used_bonus,
        delivery_cost=delivery_cost,
        comment=comment
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


async def _format_delivery_status(
        order_id: int,
        claim_id: str,
        yandex_delivery_client: YandexDeliveryClient,
        buyer_order_manager: BuyerOrderManager
) -> Tuple[str, bool]:
    """
    Получает информацию о доставке и форматирует ее.
    Возвращает (текст_статуса, флаг_нужно_полное_обновление).
    """
    # 1. Получаем ОБЩИЙ СТАТУС заявки
    claim_info = await yandex_delivery_client.get_claim_info(claim_id)
    if not claim_info:
        return "\n\n*Статус доставки:*\n❌ Не удалось получить информацию о заявке.", False

    status = claim_info.get("status")
    log.debug(f"Статус заявки {claim_id} в Яндексе: {status}")

    # 2. СИНХРОНИЗИРУЕМ статус в нашей БД, если он конечный
    was_status_updated = await buyer_order_manager.sync_order_status_from_yandex(order_id, status)

    # --- ИСПРАВЛЕНИЕ: Сначала обрабатываем конечные и простые статусы, чтобы избежать лишних запросов ---
    final_statuses_map = {
        "delivered_finish": "✅ Заказ успешно завершен",
        "returned_finish": "✅ Заказ успешно завершен (возврат)",
        "failed": "❗️Заявка не удалась",
        "cancelled": "❗️Заявка отменена",
        "cancelled_with_payment": "❗️Заявка отменена (с оплатой)",
        "cancelled_by_taxi": "❗️Заявка отменена таксопарком"
    }
    if status in final_statuses_map:
        return f"\n\n*Статус доставки:*\n{final_statuses_map[status]} (статус: {status})", was_status_updated

    if status in ("performer_lookup", "accepted", "ready_for_approval"):
        return "\n\n*Статус доставки:*\n⏳ Идет поиск курьера...", was_status_updated

    # --- ЕСЛИ СТАТУС АКТИВНЫЙ, запрашиваем ВСЕ ДЕТАЛИ параллельно ---
    lines = ["\n\n*Статус доставки:*"]
    eta_info, links_info, phone_info = await asyncio.gather(
        yandex_delivery_client.get_points_eta(claim_id),
        yandex_delivery_client.get_tracking_links(claim_id),
        yandex_delivery_client.get_courier_phone(claim_id)
    )

    # Телефон
    if phone_info and phone_info.get("phone"):
        phone = phone_info['phone']
        ext = f" (доб. {phone_info['ext']})" if phone_info.get('ext') else ""
        lines.append(f"📞 *Телефон курьера:* `{phone}{ext}`")

    # Ссылка
    if links_info:
        for point in links_info.get("route_points", []):
            if point.get("type") == "destination" and point.get("sharing_link"):
                lines.append(f"🗺️ [Отследить курьера на карте]({point['sharing_link']})")
                break
    # ETA
    if eta_info:
        for point in eta_info.get("route_points", []):
            eta_time_str = point.get("visited_at", {}).get("expected")
            if not eta_time_str:
                continue
            eta_time_utc = datetime.fromisoformat(eta_time_str)
            eta_time_local = eta_time_utc + timedelta(hours=3)  # ИСПОЛЬЗУЙТЕ ВАШ TIMEZONE_OFFSET
            time_str = eta_time_local.strftime("%H:%M")
            if point.get("type") == "destination":
                lines.append(f"🏠 Прибытие к вам: ~ *{time_str}*")

    if len(lines) == 1:
        lines.append("✅ Курьер назначен и скоро начнет движение.")

    return "\n".join(lines), was_status_updated


@client_router.callback_query(F.data.startswith("delivery:refresh:"))
async def refresh_delivery_status(
        call: CallbackQuery,
        buyer_order_manager: BuyerOrderManager,
        yandex_delivery_client: YandexDeliveryClient,
):
    # Сразу отвечаем пользователю, чтобы он видел, что кнопка сработала
    await call.answer("Обновляю информацию...")
    order_id = int(call.data.split(":")[2])

    order = await buyer_order_manager.get_order_by_id(order_id)
    if not (order and order.yandex_claim_id):
        await call.answer("Информация о заявке в Яндекс.Доставке не найдена.", show_alert=True)
        return

    # Получаем свежий текст статуса и флаг, нужно ли полностью перерисовывать карточку
    delivery_status_text, needs_full_update = await _format_delivery_status(
        order_id, order.yandex_claim_id, yandex_delivery_client, buyer_order_manager
    )

    if needs_full_update:
        # Если статус изменился на конечный (доставлен/отменен), полностью перерисовываем карточку
        log.info(f"Статус заказа #{order_id} изменился на конечный. Полное обновление карточки.")
        await show_client_order_detail(
            call,
            buyer_order_manager,
            delivery_status_text=delivery_status_text
        )
        return

    # --- ИСПРАВЛЕННАЯ ЛОГИКА ДЛЯ АКТИВНЫХ ЗАКАЗОВ ---

    # 1. Правильно отделяем основную часть сообщения от блока со статусом доставки.
    #    Это решает проблему с дублированием.
    base_text = call.message.text.split("\n\nСтатус доставки:")[0]

    # 2. Собираем полный новый текст сообщения.
    new_text = base_text + "\n\n" + delivery_status_text

    # 3. Проверяем, изменился ли текст.
    if new_text == call.message.text:
        # Если текст не изменился, сообщаем пользователю, что статус актуален.
        await call.answer("Статус актуален.", show_alert=False)
        return

    # 4. Если текст изменился, редактируем сообщение.
    try:
        await call.message.edit_text(
            new_text,
            reply_markup=call.message.reply_markup,
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        # Эта проверка на случай, если ошибка все же возникнет
        if "message is not modified" not in str(e):
            log.error(f"Ошибка при обновлении статуса доставки для заказа #{order_id}: {e}")
