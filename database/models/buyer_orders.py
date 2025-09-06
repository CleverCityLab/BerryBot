# database/models/buyer_orders.py

from enum import Enum
from typing import Optional
from datetime import date, datetime  # datetime нужен для payment_date
from decimal import Decimal  # Используем Decimal для точности с деньгами

import asyncpg
from dataclasses import dataclass


class OrderStatus(str, Enum):
    WAITING = "waiting"
    PENDING_PAYMENT = "pending_payment"
    PROCESSING = "processing"  # Добавим недостающий статус
    TRANSFERRING = "transferring"
    READY = "ready"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class DeliveryWay(str, Enum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


@dataclass
class BuyerOrders:
    # --- Старые поля ---
    id: int
    buyer_id: int
    status: OrderStatus
    delivery_way: DeliveryWay
    registration_date: date

    # --- Новые и недостающие поля, которые мы добавили в БД ---
    delivery_address: Optional[str]
    used_bonus: int
    finished_at: Optional[date]
    delivery_date: Optional[date]
    delivery_cost: Decimal  # NUMERIC(10, 2) в Python лучше представлять как Decimal
    yandex_claim_id: Optional[str]
    payment_info: Optional[dict]  # JSONB можно представить как dict
    payment_date: Optional[datetime]  # TIMESTAMP WITH TIME ZONE - это datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Optional["BuyerOrders"]:
        """
        Фабричный метод для безопасного создания экземпляра из записи asyncpg.
        Возвращает None, если запись пустая.
        """
        if not record:
            return None

        return cls(
            # Обязательные поля
            id=record["id"],
            buyer_id=record["buyer_id"],
            status=OrderStatus(record["status"]),
            delivery_way=DeliveryWay(record["delivery_way"]),
            registration_date=record["registration_date"],
            used_bonus=record["used_bonus"],

            # Опциональные поля, используем .get() для безопасности
            delivery_address=record.get("delivery_address"),
            finished_at=record.get("finished_at"),
            delivery_date=record.get("delivery_date"),

            # Поля, которые мы добавили, с преобразованием типов
            delivery_cost=record.get("delivery_cost", Decimal("0.00")),  # Decimal для денег
            yandex_claim_id=record.get("yandex_claim_id"),
            payment_info=record.get("payment_info"),
            payment_date=record.get("payment_date"),
        )
