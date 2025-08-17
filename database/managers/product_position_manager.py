from typing import Optional, Tuple

from database.async_db import AsyncDatabase


class ProductPositionManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def list_all_order_positions(self) -> list[dict]:
        sql = "SELECT id, title, price, quantity FROM product_position ORDER BY id"
        return [dict(r) for r in await self.db.fetch(sql)]

    async def list_not_empty_order_positions(self) -> list[dict]:
        sql = "SELECT id, title, price, quantity FROM product_position WHERE quantity>0 ORDER BY id"
        return [dict(r) for r in await self.db.fetch(sql)]

    async def get_order_position_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        sql = "SELECT id, title, price, quantity FROM product_position WHERE id = ANY($1)"
        return [dict(r) for r in await self.db.fetch(sql, ids)]

    async def get_order_position_by_id(self, position_id: int) -> Optional[dict]:
        sql = "SELECT id, title, price, quantity FROM product_position WHERE id = $1"
        rec = await self.db.fetchrow(sql, position_id)
        return dict(rec) if rec else None

    async def create_position(self, title: str, price: int, quantity: int) -> int:
        title = title.strip()
        sql = """
              INSERT INTO product_position (title, price, quantity)
              VALUES ($1, $2, $3)
              RETURNING id \
              """
        return int(await self.db.fetchval(sql, title, int(price), int(quantity)))

    async def update_fields(
            self,
            position_id: int,
            *,
            title: Optional[str] = None,
            price: Optional[int] = None,
            quantity: Optional[int] = None,
    ) -> None:
        sets = []
        args = []
        if title is not None:
            sets.append("title = $" + str(len(args) + 1))
            args.append(title.strip())
        if price is not None:
            sets.append("price = $" + str(len(args) + 1))
            args.append(int(price))
        if quantity is not None:
            sets.append("quantity = $" + str(len(args) + 1))
            args.append(int(quantity))

        if not sets:
            return  # нечего обновлять

        args.append(position_id)
        sql = f"UPDATE product_position SET {', '.join(sets)} WHERE id = ${len(args)}"
        await self.db.execute(sql, *args)

    async def update_title(self, position_id: int, title: str) -> None:
        sql = "UPDATE product_position SET title = $2 WHERE id = $1"
        await self.db.execute(sql, position_id, title)

    async def update_price(self, position_id: int, price: int) -> None:
        sql = "UPDATE product_position SET price = $2 WHERE id = $1"
        await self.db.execute(sql, position_id, price)

    async def update_quantity(self, position_id: int, qty: int) -> None:
        sql = "UPDATE product_position SET quantity = $2 WHERE id = $1"
        await self.db.execute(sql, position_id, qty)

    async def delete_position(self, position_id: int) -> Tuple[bool, Optional[str]]:
        try:
            await self.db.execute("DELETE FROM product_position WHERE id = $1", position_id)
            return True, None
        except Exception:
            return False, None
