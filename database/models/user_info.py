import asyncpg
from dataclasses import dataclass

@dataclass
class UserInfo:
    id: int
    tg_user_id: int

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "UserInfo":
        return cls(
            id=record["id"],
            tg_user_id=record["tg_user_id"]
        )
