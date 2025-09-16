# utils/constants.py

status_map = {
    "waiting": "Ожидает обработки",
    "pending_payment": "⏳ Ожидает оплаты",  # <-- ДОБАВЛЕНО
    "processing": "✅ Принят в работу",  # <-- ДОБАВЛЕНО
    "ready": "Готов к выдаче",
    "transferring": "🚚 В пути",
    "finished": "Завершён",
    "cancelled": "Отменён",
}

delivery_map = {
    "pickup": "Самовывоз",
    "delivery": "Доставка курьером"  # Я бы предложил чуть более полный вариант
}
