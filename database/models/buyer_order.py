from typing import Optional
from datetime import date
import asyncpg
from dataclasses import dataclass


@dataclass
class BuyerOrder:
    id: int
    position_id: int
    status: str
    delivery_way: str
    registration_date: date
    delivery_date: Optional[date]
    is_finish: str
    receipt_date: Optional[date]

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "BuyerOrder":
        return cls(
            id=record["id"],
            position_id=record["position_id"],
            status=record["status"],
            delivery_way=record["delivery_way"],
            registration_date=record["registration_date"],
            delivery_date=record.get("delivery_date"),
            is_finish=record["is_finish"],
            receipt_date=record.get("receipt_date")
        )
