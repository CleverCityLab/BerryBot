from database.async_db import AsyncDatabase


class ProductPositionManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def list_all_order_positions(self) -> list[dict]:
        sql = "SELECT id, title, price, quantity FROM product_position WHERE quantity>0 ORDER BY id"
        return [dict(r) for r in await self.db.fetch(sql)]

    async def get_order_position_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids: return []
        sql = "SELECT id, title, price, quantity FROM product_position WHERE id = ANY($1)"
        return [dict(r) for r in await self.db.fetch(sql, ids)]
