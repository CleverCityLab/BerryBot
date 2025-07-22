import asyncpg
from dataclasses import dataclass

@dataclass
class ProductPosition:
    id: int
    title: str
    price: int
    quantity: int

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "ProductPosition":
        return cls(
            id=record["id"],
            title=record["title"],
            price=record["price"],
            quantity=record["quantity"]
        )