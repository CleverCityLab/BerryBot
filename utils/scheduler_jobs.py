# utils/scheduler_jobs.py

from api.yandex_delivery import YandexDeliveryClient
from database.managers.buyer_order_manager import BuyerOrderManager
from utils.logger import get_logger

log = get_logger("[SchedulerJobs]")


async def check_delivery_statuses(
        buyer_order_manager: BuyerOrderManager,
        yandex_delivery_client: YandexDeliveryClient
):
    """
    Проверяет статусы активных доставок в Яндексе и синхронизирует их с локальной БД.
    """
    log.info("Запуск задачи синхронизации статусов Яндекс.Доставки...")

    # 1. Находим все заказы, которые сейчас должны быть в процессе доставки
    active_delivery_orders = await buyer_order_manager.get_active_yandex_deliveries()

    if not active_delivery_orders:
        log.info("Активных заказов для синхронизации с Яндексом не найдено.")
        return

    log.info(f"Найдено {len(active_delivery_orders)} активных доставок для проверки.")

    synced_count = 0
    # 2. Проверяем статус каждого заказа
    for order in active_delivery_orders:
        order_id = order['id']
        claim_id = order['yandex_claim_id']

        log.debug(f"{order_id}")

        if claim_id is None:
            await buyer_order_manager.cancel_order(order_id)

            log.info(
                f"Статус заказа #{order_id} был автоматически отменён.")

            return

        try:
            claim_info = await yandex_delivery_client.get_claim_info(claim_id)
            if not claim_info:
                log.warning(f"Не удалось получить информацию по заявке {claim_id} для заказа #{order_id}.")
                continue

            yandex_status = claim_info.get("status")

            # 3. Вызываем существующую логику синхронизации
            was_updated = await buyer_order_manager.sync_order_status_from_yandex(order_id, yandex_status)

            if was_updated:
                synced_count += 1
                log.info(
                    f"Статус заказа #{order_id} был автоматически синхронизирован."
                    f" Новый статус в Яндексе: {yandex_status}.")

        except Exception as e:
            log.exception(f"Ошибка при синхронизации статуса для заказа #{order_id} (claim_id: {claim_id}): {e}")

    log.info(f"Задача синхронизации статусов завершена. Обновлено статусов: {synced_count}.")


async def cleanup_stuck_orders(buyer_order_manager: BuyerOrderManager):
    """
    Отменяет заказы, которые не удалось создать в Яндекс.Доставке.
    """
    # Устанавливаем таймаут. Если за 20 минут заявка не создалась - отменяем.
    timeout = 20
    log.info(f"Запуск задачи очистки зависших заказов (старше {timeout} минут)...")

    try:
        cancelled_ids = await buyer_order_manager.cancel_stuck_processing_orders(timeout)
        if cancelled_ids:
            log.info(f"Очистка завершена. Отменено зависших заказов: {len(cancelled_ids)}.")
        else:
            log.info("Очистка завершена. Зависших заказов не найдено.")
    except Exception as e:
        log.exception(f"Критическая ошибка в задаче очистки зависших заказов: {e}")
