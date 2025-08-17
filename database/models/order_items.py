import asyncpg
from dataclasses import dataclass


@dataclass
class OrderItems:
    order_id: int
    position_id: int
    qty: int

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "OrderItems":
        return cls(
            order_id=record["order_id"],
            position_id=record["position_id"],
            qty=record["qty"],
        )
