from collections import namedtuple
from datetime import date
from typing import Sequence, Optional

from database.async_db import AsyncDatabase
from database.models.buyer_orders import BuyerOrders

ACTIVE_STATUSES: Sequence[str] = ("waiting", "transferring", "ready")
FINISHED_STATUSES: Sequence[str] = ("finished", "cancelled")

Item = namedtuple("Item", "title price qty")


class BuyerOrderManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def count_active_orders_by_tg(self, tg_user_id: int) -> int:
        sql = """
              SELECT COUNT(*)
              FROM buyer_orders bo
                       JOIN user_info ui ON ui.id = bo.buyer_id
              WHERE ui.tg_user_id = $1
                AND bo.status = ANY ($2::order_status[])
              """
        return await self.db.fetchval(sql, tg_user_id, list(ACTIVE_STATUSES))

    async def count_total_orders_by_tg(self, tg_user_id: int) -> int:
        sql = """
              SELECT COUNT(*)
              FROM buyer_orders bo
                       JOIN user_info ui ON ui.id = bo.buyer_id
              WHERE ui.tg_user_id = $1
              """
        return await self.db.fetchval(sql, tg_user_id)

    async def list_orders(
            self, tg_user_id: int, finished: bool
    ) -> list[BuyerOrders]:
        statuses = FINISHED_STATUSES if finished else ACTIVE_STATUSES
        sql = """
              SELECT bo.* \
              FROM buyer_orders bo \
                       JOIN user_info ui ON ui.id = bo.buyer_id
              WHERE ui.tg_user_id = $1
                AND bo.status = ANY ($2::order_status[])
              ORDER BY bo.registration_date DESC, bo.id DESC; \
              """
        recs = await self.db.fetch(sql, tg_user_id, list(statuses))
        return [BuyerOrders.from_record(r) for r in recs]

    async def get_order(self, tg_user_id: int, order_id: int) -> BuyerOrders | None:
        sql = """
              SELECT bo.*
              FROM buyer_orders bo
                       JOIN user_info ui ON ui.id = bo.buyer_id
              WHERE ui.tg_user_id = $1
                AND bo.id = $2;
              """
        rec = await self.db.fetchrow(sql, tg_user_id, order_id)
        return BuyerOrders.from_record(rec) if rec else None

    async def cancel_order(self, order_id: int) -> None:
        sql = """
              UPDATE buyer_orders
              SET status      = 'cancelled',
                  finished_at = CURRENT_DATE
              WHERE id = $1
                AND status = ANY ($2::order_status[]);
              """
        await self.db.execute(sql, order_id, list(ACTIVE_STATUSES))

    async def list_items_by_order_id(self, order_id: int) -> list[Item]:
        sql = """
              SELECT pp.title, pp.price, oi.qty
              FROM order_items oi
                       JOIN product_position pp ON pp.id = oi.position_id
              WHERE oi.order_id = $1
              ORDER BY pp.title;
              """
        recs = await self.db.fetch(sql, order_id)
        return [Item(r["title"], r["price"], r["qty"]) for r in recs]

    async def order_total_sum_by_order_id(self, order_id: int) -> int:
        sql = """
              SELECT SUM(pp.price * oi.qty) AS total
              FROM order_items oi
                       JOIN product_position pp ON pp.id = oi.position_id
              WHERE oi.order_id = $1;
              """
        return (await self.db.fetchval(sql, order_id)) or 0

    async def create_order(
            self,
            tg_user_id: int,
            items: dict[int, int],  # {position_id: qty}
            delivery_way: str,
            address: Optional[str],
            used_bonus: int,
    ) -> tuple[bool, str | None]:
        """
        Проверяем склад, создаём заказ, позиции, уменьшаем остатки
        и списываем бонусы.
        Возвращает (ok, error_message).
        """
        if not items:
            return False, "Корзина пуста"

        # одна транзакция на все действия
        async with self.db.pool.acquire() as conn:
            async with conn.transaction():
                # 1) user_id
                uid = await conn.fetchval(
                    "SELECT id FROM user_info WHERE tg_user_id = $1",
                    tg_user_id,
                )
                if uid is None:
                    return False, "Пользователь не найден"

                # 2) блокируем выбранные позиции склада
                pids = list(items.keys())
                rows = await conn.fetch(
                    """
                    SELECT id, title, quantity, price
                    FROM product_position
                    WHERE id = ANY ($1::bigint[])
                        FOR UPDATE
                    """,
                    pids,
                )
                stock = {r["id"]: r for r in rows}

                # отсутствующие id
                missing = [pid for pid in pids if pid not in stock]
                if missing:
                    return False, "Некорректные позиции: " + ", ".join(map(str, missing))

                # 3) проверяем остаток и считаем сумму
                lack_msgs = []
                order_total = 0
                for pid, qty in items.items():
                    have = stock[pid]["quantity"]
                    if qty > have:
                        lack_msgs.append(
                            f"{stock[pid]['title']} (не хватает {qty - have})"
                        )
                    order_total += stock[pid]["price"] * qty

                if lack_msgs:
                    return False, "Недостаточно на складе: " + "; ".join(lack_msgs)

                # 4) скорректируем списание бонусов: не больше доступных и суммы заказа
                cur_bonus = await conn.fetchval(
                    """
                    SELECT b.bonus_num
                    FROM buyer_info b
                             JOIN user_info u ON u.id = b.user_id
                    WHERE u.tg_user_id = $1
                        FOR UPDATE
                    """,
                    tg_user_id,
                )
                cur_bonus = int(cur_bonus or 0)
                safe_bonus = min(max(int(used_bonus or 0), 0), cur_bonus, order_total)

                # 5) создаём заказ
                delivery_date = None if delivery_way == "pickup" else date.today()
                order_id = await conn.fetchval(
                    """
                    INSERT INTO buyer_orders
                    (buyer_id, status, delivery_way, delivery_address, used_bonus, registration_date, delivery_date)
                    VALUES ($1, 'waiting', $2::delivery_way, $3, $4, CURRENT_DATE, $5)
                    RETURNING id
                    """,
                    uid,
                    delivery_way,
                    address,
                    safe_bonus,
                    delivery_date,
                )

                # 6) вставляем позиции и уменьшаем склад
                await conn.executemany(
                    """
                    INSERT INTO order_items (order_id, position_id, qty)
                    VALUES ($1, $2, $3)
                    """,
                    [(order_id, pid, qty) for pid, qty in items.items()],
                )

                await conn.executemany(
                    """
                    UPDATE product_position
                    SET quantity = quantity - $2
                    WHERE id = $1
                    """,
                    [(pid, qty) for pid, qty in items.items()],
                )

                # 7) списываем бонусы (если есть что списывать)
                if safe_bonus > 0:
                    await conn.execute(
                        """
                        UPDATE buyer_info b
                        SET bonus_num = GREATEST(b.bonus_num - $2, 0)
                        FROM user_info u
                        WHERE b.user_id = u.id
                          AND u.tg_user_id = $1
                        """,
                        tg_user_id,
                        safe_bonus,
                    )

        return True, None
