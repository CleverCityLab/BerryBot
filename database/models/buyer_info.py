from typing import Optional
import asyncpg
from dataclasses import dataclass


@dataclass
class BuyerInfo:
    user_id: int
    name_surname: str
    tel_num: str
    tg_username: Optional[str]
    address: Optional[str]
    bonus_num: int = 0

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "BuyerInfo":
        return cls(
            user_id=record["user_id"],
            name_surname=record["name_surname"],
            tel_num=record["tel_num"],
            tg_username=record.get("tg_username"),
            address=record.get("address"),
            bonus_num=record["bonus_num"]
        )
