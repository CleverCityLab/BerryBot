import logging
from math import ceil
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton, \
    InputMediaPhoto, FSInputFile

from api.yandex_delivery import geocode_address, YandexDeliveryClient
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
    get_profile_inline_keyboard,
    confirm_geoposition_kb
)

from utils.constants import status_map, delivery_map
from utils.logger import get_logger
from utils.notifications import notify_admins
from utils.phone import normalize_phone
from utils.save_image import MEDIA_PUBLIC_ROOT, MEDIA_DIR
from utils.secrets import get_admin_ids

MIN_PAYMENT_AMOUNT = 60

log = get_logger("[Bot.Client]")

client_router = Router()


# --- ВРЕМЕННЫЙ ОТЛАДОЧНЫЙ MIDDLEWARE ---
@client_router.callback_query.outer_middleware()
async def spy_middleware(handler, event: CallbackQuery, data: dict):
    state: FSMContext = data.get("state")
    if state:
        current_state = await state.get_state()
        print("🕵️‍ SPY: Перед обработкой CallbackQuery")
        print(f"   - Данные callback: {event.data}")
        print(f"   - Текущее состояние FSM: {current_state}")

    # Запускаем основной хендлер
    result = await handler(event, data)

    if state:
        new_state = await state.get_state()
        print("🕵️‍ SPY: После обработки CallbackQuery")
        print(f"   - Новое состояние FSM: {new_state}")
        print("-" * 30)

    return result


# ------------------------------


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


class ProfileEdit(StatesGroup):
    full_name = State()
    phone = State()


class CreateOrder(StatesGroup):
    choose_products = State()  # Шаг 1: Выбор товаров
    choose_delivery = State()  # Шаг 2: Выбор способа получения (самовывоз/доставка)
    enter_address = State()  # Шаг 3: Ввод адреса (только для доставки)
    confirm_geoposition = State()  # Шаг 4: Подтверждение геопозиции
    enter_porch = State()  # Шаг 5: Ввод подъезда
    enter_floor = State()  # Шаг 6: Ввод этажа
    enter_apartment = State()  # Шаг 7: Ввод квартиры
    confirm_order = State()  # Шаг 8: Финальное подтверждение со всеми расчетами
    waiting_payment = State()  # Шаг 9: Ожидание оплаты


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
async def cb_back_main(call: CallbackQuery, state: FSMContext, buyer_info_manager):
    await call.answer()
    await cleanup_client_media(call.bot, state, call.message.chat.id)
    is_admin = call.from_user.id in get_admin_ids()
    bonuses = await buyer_info_manager.get_user_bonuses_by_tg(call.from_user.id)
    try:
        await call.message.edit_text(
            text="Выбери действие: \n"
                 f"Накоплено бонусов: `{bonuses if bonuses else 0}` руб.",
            parse_mode="Markdown",
            reply_markup=get_main_inline_keyboard(is_admin),
        )
        await state.clear()
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
            reply_markup=get_orders_list_kb(orders, finished=False, page=1)
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
            reply_markup=get_orders_list_kb(orders, finished=True, page=1)
        )
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
        await handle_telegram_error(e, call=call)
        return


@client_router.callback_query(F.data.startswith("orders:page:"))
async def on_orders_page(call: CallbackQuery, buyer_order_manager):
    _, _, suffix, page_str = call.data.split(":")
    finished = (suffix == "fin")
    try:
        page = int(page_str)
    except ValueError:
        page = 1

    tg = call.from_user.id
    orders = await buyer_order_manager.list_orders(tg_user_id=tg, finished=finished)
    kb = get_orders_list_kb(orders, finished=finished, page=page)

    try:
        await call.message.edit_reply_markup(reply_markup=kb)
        await call.answer()
    except TelegramBadRequest as e:
        log.error(f"[Bot.Client] Ошибка при изменении клавиатуры: {e}")
        await handle_telegram_error(e, call=call)


@client_router.callback_query(F.data.startswith("order:"), StateFilter(None))
async def order_detail(call: CallbackQuery, buyer_order_manager, *, delivery_status_text: str | None = None):
    """
    Показывает детали заказа. Может принимать дополнительный текст о статусе доставки.
    """
    await call.answer()
    _, oid, kind = call.data.split(":")
    order = await buyer_order_manager.get_order(call.from_user.id, int(oid))
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return

    items = await buyer_order_manager.list_items_by_order_id(order.id)
    items_text = "\n".join([f"• {it.title} ×{it.qty} — {it.price * it.qty} ₽" for it in items]) if items else "пусто"

    total = await buyer_order_manager.order_total_sum_by_order_id(order.id)
    status_txt = status_map.get(order.status.value, order.status.value)
    delivery_txt = delivery_map.get(order.delivery_way.value, order.delivery_way.value)

    # Собираем основной текст по частям
    text_parts = [
        f"Заказ №{order.id}",
        f"Товары:\n{items_text}",
        f"Итого: {total} ₽",
        f"Способ получения: {delivery_txt}",
        f"Статус: {status_txt}",
        f"Дата оформления: {order.registration_date:%d.%m.%Y}"
    ]
    if order.delivery_date:
        text_parts.append(f"Плановая дата получения: {order.delivery_date:%d.%m.%Y}")

    # Если был передан текст статуса доставки (из функции обновления), добавляем его
    if delivery_status_text:
        text_parts.append(delivery_status_text)

    text = "\n\n".join(text_parts)

    try:
        # Отправляем без parse_mode, как вы и хотели
        await call.message.edit_text(
            text,
            reply_markup=get_order_detail_kb(order),
            disable_web_page_preview=True
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            log.error(f"[Bot.Client] Ошибка при изменении сообщения: {e}")
            await handle_telegram_error(e, call=call)


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

    status_txt = status_map.get(order.status.value, order.status.value)
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
async def order_cancel_yes(
        call: CallbackQuery,
        bot: Bot,
        buyer_order_manager: BuyerOrderManager,
        yandex_delivery_client: YandexDeliveryClient,
        buyer_info_manager: BuyerInfoManager,
):
    order_id = int(call.data.split(":")[1])
    log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Процесс запущен пользователем {call.from_user.id}")

    order = await buyer_order_manager.get_order_by_id(order_id)
    if not order:
        log.warning(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Заказ не найден в БД.")
        await call.answer("Заказ не найден.", show_alert=True)
        return

    if order.yandex_claim_id:
        await call.answer("Проверяем условия отмены в Яндексе...")
        log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Найден claim_id: {order.yandex_claim_id}. Проверяем условия.")

        # 1. Запрашиваем информацию для получения ВЕРСИИ
        claim_info = await yandex_delivery_client.get_claim_info(order.yandex_claim_id)
        if not claim_info:
            log.error(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Не удалось получить информацию о заявке от Яндекса.")
            await call.answer("Не удалось получить информацию о заявке в Яндексе.", show_alert=True)
            return

        current_version = claim_info.get("version", 1)
        log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Текущая версия заявки: {current_version}")

        # 2. Узнаем условия отмены
        cancel_info = await yandex_delivery_client.get_cancellation_info(order.yandex_claim_id)

        if not cancel_info or cancel_info.get("cancel_state") != "free":
            price_info = (f"(стоимость платной отмены:"
                          f" {cancel_info.get('price', 'N/A')} руб."
                          f")") if cancel_info and cancel_info.get(
                "cancel_state") == "paid" else ""

            cancel_state = cancel_info.get("cancel_state") if cancel_info else "неизвестно"
            log.warning(
                f"[ОТМЕНА ЗАКАЗА #{order_id}] - Отмена не является бесплатной. "
                f"Статус отмены: {cancel_state}. Процесс прерван.")

            # Редактируем сообщение, чтобы показать причину
            await call.message.edit_text(
                f"❗️Заказ №{order.id} уже нельзя отменить бесплатно {price_info}.\n\n"
                "Вероятно, курьер уже назначен или в пути.\n"
                "Для решения вопроса свяжитесь с поддержкой.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к заказу", callback_data=f"order:{order.id}:act")]
                ])
            )
            await call.answer()  # Убираем show_alert, так как уже есть сообщение
            return

        # 3. Отменяем заявку в Яндексе
        log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Отмена бесплатна. Отправляем запрос на отмену...")
        is_cancelled_on_yandex = await yandex_delivery_client.cancel_claim(
            claim_id=order.yandex_claim_id,
            cancel_state="free",
            version=current_version
        )
        if not is_cancelled_on_yandex:
            log.error(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Яндекс вернул ошибку при отмене.")
            await call.answer("Не удалось отменить заказ в системе доставки. Свяжитесь с поддержкой.", show_alert=True)
            return

        log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Заявка в Яндексе успешно отменена.")

    # 4. Отменяем заказ в нашей БД
    await buyer_order_manager.cancel_order(order_id)
    log.info(f"[ОТМЕНА ЗАКАЗА #{order_id}] - Заказ успешно отменен в локальной БД.")

    await call.answer("Ваш заказ успешно отменён!", show_alert=True)
    # --- НАЧАЛО БЛОКА УВЕДОМЛЕНИЯ АДМИНУ ---
    buyer_data = await buyer_info_manager.get_profile_by_tg(call.from_user.id)
    admin_text = (
        f"❌ *Клиент отменил заказ №{order_id}*\n\n"
        f"Пользователь: {buyer_data.get('name_surname')} (@{buyer_data.get('tg_username', 'не указан')})"
    )
    # Отправляем уведомление всем админам без клавиатуры
    await notify_admins(bot, admin_text)
    # --- КОНЕЦ БЛОКА УВЕДОМЛЕНИЯ ---

    # 4. Обновляем и показываем пользователю список его активных заказов
    orders = await buyer_order_manager.list_orders(tg_user_id=call.from_user.id, finished=False)
    header = f"Кол-во ожидаемых заказов: `{len(orders)}`"
    try:
        await call.message.edit_text(
            header,
            parse_mode="Markdown",
            reply_markup=get_orders_list_kb(orders, finished=False)
        )
    except TelegramBadRequest as e:
        # Если не получилось отредактировать, отправляем новое сообщение
        await handle_telegram_error(e, call=call)
        await call.message.answer(header, parse_mode="Markdown",
                                  reply_markup=get_orders_list_kb(orders, finished=False))


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


def abs_image_path(rel_path: str) -> str:
    # rel_path вида 'product_images/xxx.jpg' -> абсолютный путь
    p = Path(rel_path)
    if p.is_absolute():
        return str(p)
    # отрезаем префикс 'product_images/'
    rel_name = str(p)
    if rel_name.startswith(f"{MEDIA_PUBLIC_ROOT}/"):
        rel_name = rel_name[len(MEDIA_PUBLIC_ROOT) + 1:]
    return str(MEDIA_DIR / rel_name)


CLIENT_MEDIA_IDS_KEY = "client_media_msg_ids"


async def cleanup_client_media(bot, state, chat_id: int):
    data = await state.get_data()
    ids = data.get(CLIENT_MEDIA_IDS_KEY, [])
    for mid in ids:
        try:
            await bot.delete_message(chat_id, mid)
        except TelegramBadRequest:
            pass
    await state.update_data(**{CLIENT_MEDIA_IDS_KEY: []})


async def send_products_album(target: Message | CallbackQuery, products_page: list[dict], state):
    if isinstance(target, Message):
        chat_id = target.chat.id
        base = target
        bot = target.bot
    else:
        chat_id = target.message.chat.id
        base = target.message
        bot = target.bot

    await cleanup_client_media(bot, state, chat_id)

    if not products_page:
        return

    media: list[InputMediaPhoto] = []
    lines: list[str] = []

    for i, p in enumerate(products_page, start=1):
        img = p.get("image_path")
        if not img:
            continue
        path = abs_image_path(img)
        lines.append(f"{i}) {p['title']} — {p['price']} ₽")
        media.append(InputMediaPhoto(media=FSInputFile(path)))
        if len(media) == 10:
            break

    if not media:
        return

    media[-1].caption = "\n".join(lines)
    media[-1].parse_mode = "Markdown"

    try:
        msgs = await base.answer_media_group(media=media)
    except TelegramBadRequest:
        for m in media:
            m.caption = None
        msgs = await base.answer_media_group(media=media)
        await base.answer("\n".join(lines), parse_mode="Markdown")

    await state.update_data(**{CLIENT_MEDIA_IDS_KEY: [m.message_id for m in msgs]})


@client_router.callback_query(F.data.startswith("cart:page:"))
async def on_cart_page(call: CallbackQuery, state: FSMContext, product_position_manager):
    try:
        page = int(call.data.split(":")[-1])
    except ValueError:
        await call.answer()
        return

    data = await state.get_data()
    cart: dict[int, int] = data.get("cart", {})
    products = await product_position_manager.list_not_empty_order_positions()

    total_pages = max(1, ceil(len(products) / 10))
    page = max(1, min(page, total_pages))
    await state.update_data(page=page)

    start = (page - 1) * 10
    end = start + 10
    await send_products_album(call, products[start:end], state)

    kb = get_all_products(products, cart, page=page)
    try:
        await call.message.edit_text("Выберите товары:", reply_markup=kb)
    except Exception:
        await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()


@client_router.callback_query(CreateOrder.choose_delivery, F.data == "cart:back")
async def back_from_delivery_to_cart(call: CallbackQuery, state: FSMContext, product_position_manager):
    data = await state.get_data()
    cart: dict[int, int] = data.get("cart", {})
    page: int = data.get("page", 1)

    products = await product_position_manager.list_not_empty_order_positions()

    total_pages = max(1, ceil(len(products) / 10))
    page = max(1, min(page, total_pages))
    await state.set_state(CreateOrder.choose_products)
    await state.update_data(page=page)

    start = (page - 1) * 10
    end = start + 10
    await send_products_album(call, products[start:end], state)

    kb = get_all_products(products, cart, page=page)
    try:
        await call.message.edit_text("Выберите товары:", reply_markup=kb)
    except Exception:
        await call.message.edit_reply_markup(reply_markup=kb)
    await call.answer()


@client_router.callback_query(F.data == "create-order")
async def start_create(call: CallbackQuery, state: FSMContext, product_position_manager: ProductPositionManager):
    await state.clear()
    await state.update_data(cart={}, page=1)
    products = await product_position_manager.list_not_empty_order_positions()
    start, end = 0, 10
    await send_products_album(call, products[start:end], state)

    kb = get_all_products(products, cart={}, page=1)
    await call.message.edit_text("Выберите товары:", reply_markup=kb)

    await state.set_state(CreateOrder.choose_products)
    await call.answer()


@client_router.callback_query(CreateOrder.confirm_order, F.data == "addr:back")
async def back_from_confirm_to_delivery(call: CallbackQuery, state: FSMContext):
    """
    Возвращает пользователя с экрана финального подтверждения
    обратно к выбору способа доставки.
    """
    await call.answer()

    # Очищаем данные, связанные с доставкой, чтобы избежать путаницы
    await state.update_data(address=None, delivery_cost=None)

    await call.message.edit_text(
        "Как вы хотите получить заказ?",
        reply_markup=choice_of_delivery()
    )
    await state.set_state(CreateOrder.choose_delivery)


@client_router.callback_query(CreateOrder.enter_address, F.data.startswith("addr:"))
async def handle_address_source_choice(
        call: CallbackQuery,
        state: FSMContext,
        bot: Bot,  # Нам понадобится bot для отправки карты
        buyer_info_manager: BuyerInfoManager
):
    """
    Обрабатывает кнопки "Использовать сохраненный" или "Ввести вручную".
    """
    await call.answer()
    action = call.data.split(":")[1]

    if action == "enter":
        await call.message.edit_text("Введите основную часть адреса через запятую (город, улица, дом).\n\n"
                                     "Например: <b>Нижний Новгород, Большая Покровская, 1</b>", parse_mode="HTML")
        return

    if action == "use_saved":
        saved_address = await buyer_info_manager.get_address_by_tg(call.from_user.id)

        if not saved_address:
            await call.message.answer("У вас нет сохраненного адреса. Пожалуйста, введите его вручную.")
            await call.message.edit_text("Введите основную часть адреса через запятую (город, улица, дом).\n\n"
                                         "Например: <b>Нижний Новгород, Большая Покровская, 1</b>", parse_mode="HTML")
            return

        await call.message.edit_text("⏳ Ищу сохраненный адрес на карте...")

        coords = await geocode_address(saved_address)
        if not coords:
            await call.message.answer("Не удалось найти ваш сохраненный адрес на карте. Попробуйте ввести его вручную.")
            return

        lon, lat = coords
        await state.update_data(address=saved_address, latitude=lat, longitude=lon)
        await state.set_state(CreateOrder.confirm_geoposition)

        await bot.send_location(chat_id=call.message.chat.id, latitude=lat, longitude=lon)
        await call.message.answer(
            "Я нашел ваш сохраненный адрес здесь. Все верно?",
            reply_markup=confirm_geoposition_kb()
        )


# Обработчик PreCheckoutQuery
@client_router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    # Здесь можно добавить дополнительную проверку (например, наличие товара)
    order_id = int(pre_checkout_query.invoice_payload.split(":")[1])
    log.info(f"Получен pre-checkout запрос для заказа #{order_id}")

    # Подтверждаем, что готовы принять платеж
    await pre_checkout_query.answer(ok=True)
    log.info(f"Ответили ok=True на pre-checkout для заказа #{order_id}")


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
