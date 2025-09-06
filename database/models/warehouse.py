import asyncpg
from dataclasses import dataclass


@dataclass
class Warehouse:
    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    contact_name: str
    contact_phone: str
    is_active: bool
    is_default: bool

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "Warehouse":
        return cls(
            id=record["id"],
            name=record["name"],
            address=record["address"],
            latitude=record["latitude"],
            longitude=record["longitude"],
            contact_name=record["contact_name"],
            contact_phone=record["contact_phone"],
            is_active=record["is_active"],
            is_default=record["is_default"],
        )
