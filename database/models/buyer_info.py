from typing import Optional
import asyncpg
from dataclasses import dataclass


@dataclass
class BuyerInfo:
    tg_user_id: int
    name_surname: str
    tel_num: int
    tg_username: Optional[str]
    address: Optional[str]
    bonus_num: int

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "BuyerInfo":
        return cls(
            tg_user_id=record["tg_user_id"],
            name_surname=record["name_surname"],
            tel_num=record["tel_num"],
            tg_username=record.get("tg_username"),
            address=record.get("address"),
            bonus_num=record["bonus_num"]
        )