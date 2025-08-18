from enum import Enum
from typing import Optional
from datetime import date
import asyncpg
from dataclasses import dataclass


class OrderStatus(str, Enum):
    WAITING = "waiting"
    PENDING_PAYMENT = "pending_payment"
    TRANSFERRING = "transferring"
    READY = "ready"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class DeliveryWay(str, Enum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


@dataclass
class BuyerOrders:
    id: int
    buyer_id: int
    status: OrderStatus
    delivery_way: DeliveryWay
    registration_date: date
    finished_at: Optional[date]
    delivery_date: Optional[date]

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "BuyerOrders":
        return cls(
            id=record["id"],
            buyer_id=record["buyer_id"],
            status=OrderStatus(record["status"]),
            delivery_way=DeliveryWay(record["delivery_way"]),
            registration_date=record["registration_date"],
            finished_at=record.get("finished_at"),
            delivery_date=record.get("delivery_date"),
        )
