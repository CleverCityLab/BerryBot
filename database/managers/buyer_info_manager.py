from typing import Optional

from database.async_db import AsyncDatabase


class BuyerInfoManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def is_registered(self, user_id: int) -> bool:
        sql = "SELECT EXISTS (SELECT 1 FROM buyer_info WHERE user_id = $1);"
        return await self.db.fetchval(sql, user_id)

    async def upsert_address_details(
            self,
            tg_user_id: int,
            full_address: str,
            porch: Optional[str],
            floor: Optional[str],
            apartment: Optional[str]
    ):
        """
        Обновляет или вставляет (UPSERT) детализированный адрес пользователя.
        """
        # Сначала получаем внутренний user_id по tg_user_id
        user_id = await self.db.fetchval("SELECT id FROM user_info WHERE tg_user_id = $1", tg_user_id)
        if not user_id:
            # Такого быть не должно, если пользователь дошел до этого шага, но проверка важна
            return

        sql = """
            INSERT INTO buyer_info (user_id, address, porch, floor, apartment, name_surname, tel_num)
            VALUES ($1, $2, $3, $4, $5, 'не указано', 'не указан')
            ON CONFLICT (user_id) DO UPDATE SET
                address = EXCLUDED.address,
                porch = EXCLUDED.porch,
                floor = EXCLUDED.floor,
                apartment = EXCLUDED.apartment;
            """
        await self.db.execute(sql, user_id, full_address, porch, floor, apartment)

    async def get_profile_by_tg(self, tg_user_id: int) -> Optional[dict]:
        """
        Возвращает полный профиль пользователя, включая детали адреса.
        """
        sql = """
            SELECT b.name_surname, b.tel_num, b.tg_username, b.address, b.porch, b.floor, b.apartment
            FROM buyer_info b
            JOIN user_info u ON u.id = b.user_id
            WHERE u.tg_user_id = $1
            """
        record = await self.db.fetchrow(sql, tg_user_id)
        return dict(record) if record else None

    async def create_buyer_info(
            self,
            tg_user_id: int,
            name_surname: str,
            tel_num: str,
            tg_username: str | None,
    ) -> None:
        user_id = await self.db.fetchval(
            "SELECT id FROM user_info WHERE tg_user_id = $1", tg_user_id
        )
        sql = """
              INSERT INTO buyer_info (user_id, name_surname, tel_num, tg_username)
              VALUES ($1, $2, $3, $4)
              ON CONFLICT (user_id) DO UPDATE
                  SET name_surname = EXCLUDED.name_surname,
                      tel_num      = EXCLUDED.tel_num,
                      tg_username  = EXCLUDED.tg_username \
              """
        await self.db.execute(sql, user_id, name_surname, tel_num, tg_username)

    async def get_user_bonuses_by_id(self, user_id: int) -> int:
        sql = "SELECT bonus_num FROM buyer_info WHERE user_id = $1;"
        return await self.db.fetchval(sql, user_id)

    async def get_user_bonuses_by_tg(self, tg_user_id: int) -> int:
        sql = """
              SELECT COALESCE(b.bonus_num, 0)
              FROM buyer_info b
                       JOIN user_info u ON u.id = b.user_id
              WHERE u.tg_user_id = $1;
              """
        bonuses = await self.db.fetchval(sql, tg_user_id)
        return bonuses or 0

    async def get_address_by_tg(self, tg_user_id: int) -> str | None:
        sql = """
              SELECT b.address
              FROM buyer_info b
                       JOIN user_info u ON u.id = b.user_id
              WHERE u.tg_user_id = $1
              """
        return await self.db.fetchval(sql, tg_user_id)

    async def update_address_by_tg(self, tg_user_id: int, address: str) -> None:
        sql = """
              UPDATE buyer_info b
              SET address = $2
              FROM user_info u
              WHERE b.user_id = u.id
                AND u.tg_user_id = $1
              """
        await self.db.execute(sql, tg_user_id, address)

    #    async def get_profile_by_tg(self, tg_user_id: int):
    #        sql = """
    #              SELECT b.name_surname, b.tel_num, b.tg_username
    #              FROM buyer_info b
    #                       JOIN user_info u ON u.id = b.user_id
    #              WHERE u.tg_user_id = $1 \
    #              """
    #        return await self.db.fetchrow(sql, tg_user_id)

    async def update_full_name_by_tg(self, tg_user_id: int, name_surname: str) -> None:
        sql = """
              UPDATE buyer_info b
              SET name_surname = $2
              FROM user_info u
              WHERE b.user_id = u.id
                AND u.tg_user_id = $1
              """
        await self.db.execute(sql, tg_user_id, name_surname)

    async def update_phone_by_tg(self, tg_user_id: int, tel_num_e164: str) -> None:
        sql = """
              UPDATE buyer_info b
              SET tel_num = $2
              FROM user_info u
              WHERE b.user_id = u.id
                AND u.tg_user_id = $1
              """
        await self.db.execute(sql, tg_user_id, tel_num_e164)

    async def upsert_username_by_tg(self, tg_user_id: int, username: str | None) -> None:
        sql = """
              UPDATE buyer_info b
              SET tg_username = $2
              FROM user_info u
              WHERE b.user_id = u.id
                AND u.tg_user_id = $1
              """
        await self.db.execute(sql, tg_user_id, username)
