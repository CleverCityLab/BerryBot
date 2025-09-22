from dataclasses import dataclass
from typing import Optional
import asyncpg
from enum import Enum


class PaymentStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    canceled = "canceled"


@dataclass
class Payment:
    id: int                     # id записи в БД
    tg_user_id: int             # от кого платеж
    amount: float               # сумма
    yookassa_id: str            # id платежа в Юкассе
    status: PaymentStatus       # статус
    order_id: Optional[int]     # если есть связь с заказом

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "Payment":
        return cls(
            id=record["id"],
            tg_user_id=record["tg_user_id"],
            amount=record["amount"],
            yookassa_id=record["yookassa_id"],
            status=PaymentStatus(record["status"]),
            order_id=record.get("order_id")
        )
