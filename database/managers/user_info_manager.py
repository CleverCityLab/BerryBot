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
