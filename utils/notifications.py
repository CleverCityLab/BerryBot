# utils/notifications.py
import logging
from typing import Dict, List, Tuple, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from database.models.buyer_orders import BuyerOrders
from database.managers.buyer_order_manager import Item
from keyboards.client import get_main_inline_keyboard
from utils.secrets import get_admin_ids  # Импортируем ID администраторов

log = logging.getLogger(__name__)


async def notify_admins(bot: Bot, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None):
    """
    Отправляет сообщение всем администраторам из списка ADMIN_IDS.
    """
    admin_ids = get_admin_ids()
    if not admin_ids:
        log.warning("Список ADMIN_IDS пуст. Уведомление не будет отправлено.")
        return

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except TelegramBadRequest as e:
            # Обрабатываем возможные ошибки: бот заблокирован админом, неверный ID и т.д.
            log.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")
        except Exception as e:
            log.exception(f"Непредвиденная ошибка при отправке уведомления администратору {admin_id}: {e}")


def format_order_for_admin(
        order: BuyerOrders,
        buyer_data: Optional[Dict],
        items: List[Item]
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Форматирует красивое и информативное сообщение о новом заказе для администратора.
    Принимает объект заказа и список товаров.
    """
    items_text_lines = []
    for item in items:
        items_text_lines.append(f"• {item.title} x {item.qty} шт. = {item.price * item.qty} ₽")
    items_text = "\n".join(items_text_lines)

    total_goods = sum(item.price * item.qty for item in items)
    delivery_cost = float(order.delivery_cost)
    used_bonus = order.used_bonus
    total_to_pay = total_goods + delivery_cost - used_bonus

    delivery_way_map = {"pickup": "Самовывоз", "delivery": "Доставка курьером"}
    delivery_way_text = delivery_way_map.get(order.delivery_way.value)  # Используем .value для ENUM

    message_lines = [
        f"🎉 *Новый оплаченный заказ №{order.id}*",
        "*- - - - - - - - - - - - - - - - -*",
        "👤 *Клиент:*",
    ]
    if buyer_data:
        message_lines.extend([
            f"   Имя: {buyer_data.get('name_surname')}",
            f"   Телефон: `{buyer_data.get('tel_num')}`",
            f"   Telegram: @{buyer_data.get('tg_username', 'не указан')}",
        ])

    message_lines.extend([
        "*- - - - - - - - - - - - - - - - -*",
        "📋 *Состав заказа:*",
        items_text,
        "*- - - - - - - - - - - - - - - - -*",
        "🚚 *Доставка:*",
        f"   Способ: *{delivery_way_text}*",
    ])

    if delivery_way_text == "Доставка курьером":
        message_lines.append(f"   Адрес: `{order.delivery_address}`")
        if order.yandex_claim_id:
            message_lines.append("   Яндекс.Доставка: `Заявка создана`")
        else:
            message_lines.append("   Яндекс.Доставка: `❗️Не удалось создать заявку`")

    message_lines.extend([
        "*- - - - - - - - - - - - - - - - -*",
        "💰 *Финансы:*",
        f"   Товары: `{total_goods}` ₽",
        f"   Доставка: `{delivery_cost}` ₽",
        f"   Бонусы: `- {used_bonus}` ₽",
        f"   *Итого:* `{max(0.0, total_to_pay):.2f}` ₽",
    ])

    final_text = "\n".join(message_lines)
    # Создаем клавиатуру главного меню для администратора
    admin_keyboard = get_main_inline_keyboard(is_admin=True)

    # Возвращаем и текст, и клавиатуру
    return final_text, admin_keyboard
