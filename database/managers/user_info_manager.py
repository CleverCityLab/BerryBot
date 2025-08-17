from database.async_db import AsyncDatabase


class UserInfoManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def add_user(self, tg_user_id: int) -> int:
        insert_sql = """
                     INSERT INTO user_info (tg_user_id)
                     VALUES ($1)
                     ON CONFLICT (tg_user_id) DO NOTHING
                     RETURNING id; \
                     """

        user_id = await self.db.fetchval(insert_sql, tg_user_id)
        if user_id is not None:
            return user_id

        select_sql = "SELECT id FROM user_info WHERE tg_user_id = $1;"
        return await self.db.fetchval(select_sql, tg_user_id)

    async def list_all_tg_user_ids(self) -> list[int]:
        sql = "SELECT tg_user_id FROM user_info ORDER BY id"
        rows = await self.db.fetch(sql)
        return [int(r["tg_user_id"]) for r in rows]

    async def count_all(self) -> int:
        return int(await self.db.fetchval("SELECT COUNT(*) FROM user_info"))
