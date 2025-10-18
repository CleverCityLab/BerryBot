from typing import Optional, Tuple

from database.async_db import AsyncDatabase


class ProductPositionManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def list_all_order_positions(self) -> list[dict]:
        sql = "SELECT id, title, price, quantity FROM product_position ORDER BY id"
        return [dict(r) for r in await self.db.fetch(sql)]

    async def list_not_empty_order_positions(self) -> list[dict]:
        sql = "SELECT id, title, price, quantity, weight_kg, image_path FROM product_position WHERE quantity>0 ORDER BY id"
        return [dict(r) for r in await self.db.fetch(sql)]

    async def get_order_position_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        # Выбираем все поля с помощью '*'
        sql = "SELECT * FROM product_position WHERE id = ANY($1)"
        records = await self.db.fetch(sql, ids)
        return [dict(r) for r in records]

    async def get_order_position_by_id(self, pos_id: int) -> Optional[dict]:
        # Просто выбираем все поля
        sql = "SELECT * FROM product_position WHERE id = $1"
        rec = await self.db.fetchrow(sql, pos_id)
        return dict(rec) if rec else None

    async def create_position(
            self,
            title: str, price: int, quantity: int,
            weight_kg: float, length_m: float, width_m: float, height_m: float, image_path: str,
    ) -> int:
        sql = """
              INSERT INTO product_position (title, price, quantity, weight_kg, length_m, width_m, height_m, image_path)
              VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
              RETURNING id \
              """
        return await self.db.fetchval(sql, title, price, quantity, weight_kg, length_m,
                                      width_m, height_m, image_path)

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

    async def update_weight(self, pos_id: int, weight_kg: float):
        """Обновляет вес товара."""
        sql = "UPDATE product_position SET weight_kg = $1 WHERE id = $2"
        await self.db.execute(sql, weight_kg, pos_id)

    async def update_dims(self, pos_id: int, length_m: float, width_m: float, height_m: float):
        """Обновляет габариты товара."""
        sql = "UPDATE product_position SET length_m = $1, width_m = $2, height_m = $3 WHERE id = $4"
        await self.db.execute(sql, length_m, width_m, height_m, pos_id)
