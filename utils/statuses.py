# utils/statuses.py

# --- 1. ОПРЕДЕЛЕНИЕ СТАТУСОВ ---
S_WAITING = "waiting"  # Устарел, но может использоваться в старых заказах
S_PENDING_PAYMENT = "pending_payment"  # Создан, ждет оплаты
S_PROCESSING = "processing"  # Оплачен, в обработке (сборка/ожидание)
S_READY = "ready"  # Готов к самовывозу
S_TRANSFERRING = "transferring"  # Передан в доставку
S_FINISHED = "finished"  # Успешно завершен
S_CANCELLED = "cancelled"  # Отменен

# --- 2. ГРУППЫ СТАТУСОВ (используем множества `{}` для производительности) ---

# Статусы, при которых заказ считается "в работе"
ACTIVE_STATUSES = {
    S_PENDING_PAYMENT,
    S_PROCESSING,
    S_READY,
    S_TRANSFERRING,
}

# Статусы, при которых заказ считается "завершенным"
FINISHED_STATUSES = {
    S_FINISHED,
    S_CANCELLED,
}

# Статусы, при которых заказ ожидает, чтобы его забрали (либо клиент, либо курьер)
AWAITING_PICKUP = {
    S_READY,
}

# Статусы, из которых администратор может принудительно отменить заказ
CANCELLABLE_STATUSES = {
    S_PENDING_PAYMENT,
    S_PROCESSING,
    S_READY,
}

# --- 3. ЛОГИКА ПЕРЕХОДОВ СТАТУСОВ (для кнопок в админке) ---
ALLOWED_FROM = {
    # Чтобы пометить "Готов к выдаче", заказ должен быть оплачен/обработан
    S_READY: {S_PROCESSING},
    # Чтобы пометить "Передан в доставку", заказ должен быть оплачен/обработан
    S_TRANSFERRING: {S_PROCESSING},
    # Чтобы "Завершить", заказ должен быть готов к выдаче или уже в пути
    S_FINISHED: {S_READY, S_TRANSFERRING},
}
