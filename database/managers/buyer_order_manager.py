from collections import namedtuple
from datetime import date
from typing import Optional

from database.async_db import AsyncDatabase
from database.models.buyer_orders import BuyerOrders

from utils.statuses import (
    ACTIVE_STATUSES, FINISHED_STATUSES, AWAITING_PICKUP,
    ALLOWED_FROM, S_FINISHED, S_CANCELLED
)

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

    async def cancel_order(self, order_id: int):
        async with self.db.pool.acquire() as conn:
            async with conn.transaction():
                # 1. Получаем информацию о заказе и товарах в нем
                order_info = await conn.fetchrow(
                    "SELECT buyer_id, used_bonus, status FROM buyer_orders WHERE id = $1 FOR UPDATE", order_id)

                items_to_return = await conn.fetch("SELECT position_id, qty FROM order_items WHERE order_id = $1",
                                                   order_id)

                # 2. Возвращаем товары на склад
                if items_to_return:
                    await conn.executemany(
                        "UPDATE product_position SET quantity = quantity + $2 WHERE id = $1",
                        [(item['position_id'], item['qty']) for item in items_to_return]
                    )

                # 3. Возвращаем бонусы пользователю
                if order_info['used_bonus'] > 0:
                    await conn.execute(
                        "UPDATE buyer_info SET bonus_num = bonus_num + $1 WHERE user_id = $2",
                        order_info['used_bonus'], order_info['buyer_id']
                    )

                # 4. Обновляем статус заказа
                await conn.execute("UPDATE buyer_orders SET status = 'cancelled' WHERE id = $1", order_id)

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
    ) -> tuple[Optional[int], str | None]:  # ## <<< ИЗМЕНЕНО: возвращает (order_id | None, error | None)
        """
        Проверяем склад, создаём заказ со статусом 'pending_payment',
        позиции, уменьшаем остатки и списываем бонусы.
        Возвращает (order_id, error_message).
        """
        if not items:
            return None, "Корзина пуста"  # ## <<< ИЗМЕНЕНО

        # одна транзакция на все действия
        async with self.db.pool.acquire() as conn:
            async with conn.transaction():
                # 1) user_id
                uid = await conn.fetchval(
                    "SELECT id FROM user_info WHERE tg_user_id = $1",
                    tg_user_id,
                )
                if uid is None:
                    return None, "Пользователь не найден"  # ## <<< ИЗМЕНЕНО

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
                    return None, "Некорректные позиции: " + ", ".join(map(str, missing))  # ## <<< ИЗМЕНЕНО

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
                    return None, "Недостаточно на складе: " + "; ".join(lack_msgs)  # ## <<< ИЗМЕНЕНО

                # 4) скорректируем списание бонусов
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
                    VALUES ($1, 'pending_payment', $2::delivery_way, $3, $4, CURRENT_DATE, $5)
                    RETURNING id
                    """,  # ## <<< ИЗМЕНЕНО: статус 'pending_payment'
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

                # 7) списываем бонусы
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

        return order_id, None  # ## <<< ИЗМЕНЕНО: возвращаем ID заказа

    async def get_order_by_id(self, order_id: int) -> BuyerOrders | None:
        rec = await self.db.fetchrow("SELECT * FROM buyer_orders WHERE id = $1", order_id)
        return BuyerOrders.from_record(rec) if rec else None

    async def admin_set_status(self, order_id: int, to_status: str) -> bool:
        # читаем текущее состояние
        row = await self.db.fetchrow(
            "SELECT status, delivery_way FROM buyer_orders WHERE id = $1",
            order_id,
        )
        if not row:
            return False

        cur, way = row["status"], row["delivery_way"]

        allowed_from = set(ALLOWED_FROM.get(to_status, set()))
        if to_status == S_FINISHED:
            allowed_from = {"ready"} if way == "pickup" else {"transferring"}

        if cur not in allowed_from:
            return False

        val = await self.db.fetchval(
            """
            UPDATE buyer_orders
            SET status      = $2::order_status,
                finished_at = CASE
                                  WHEN $2::order_status = ANY ($3::order_status[]) THEN CURRENT_DATE
                                  ELSE finished_at
                    END
            WHERE id = $1
              AND status = ANY ($4::order_status[])
            RETURNING 1
            """,
            order_id,
            to_status,
            [S_FINISHED, S_CANCELLED],
            list(allowed_from),
        )
        return bool(val)

    async def admin_cancel(self, order_id: int) -> bool:
        updated = await self.db.execute(
            "UPDATE buyer_orders SET status = $2, finished_at = CURRENT_DATE "
            "WHERE id = $1 AND status = ANY($3::order_status[])",
            order_id, S_CANCELLED, ["waiting", "ready"]
        )
        return updated.upper().startswith("UPDATE")

    async def admin_today_revenue(self) -> int:
        sql = """
              SELECT COALESCE(SUM(t.sum - t.used), 0)::int
              FROM (SELECT o.id, \
                           COALESCE(SUM(p.price * i.qty), 0) AS sum, \
                           COALESCE(o.used_bonus, 0)         AS used \
                    FROM buyer_orders o \
                             JOIN order_items i ON i.order_id = o.id \
                             JOIN product_position p ON p.id = i.position_id \
                    WHERE o.status = 'finished' \
                      AND o.finished_at = CURRENT_DATE \
                    GROUP BY o.id, o.used_bonus) t \
              """
        return int(await self.db.fetchval(sql))

    async def admin_count_total(self) -> int:
        return int(await self.db.fetchval("SELECT COUNT(*) FROM buyer_orders"))

    async def admin_count_active(self) -> int:
        sql = "SELECT COUNT(*) FROM buyer_orders WHERE status = ANY($1::order_status[])"
        return int(await self.db.fetchval(sql, list(ACTIVE_STATUSES)))

    async def admin_count_awaiting_pickup(self) -> int:
        sql = "SELECT COUNT(*) FROM buyer_orders WHERE status = ANY($1::order_status[])"
        return int(await self.db.fetchval(sql, list(AWAITING_PICKUP)))

    async def admin_list_orders(self, finished: bool) -> list[dict]:
        statuses = FINISHED_STATUSES if finished else ACTIVE_STATUSES
        sql = """
              SELECT id, registration_date
              FROM buyer_orders
              WHERE status = ANY ($1::order_status[])
              ORDER BY registration_date DESC, id DESC \
              """
        return [dict(r) for r in await self.db.fetch(sql, list(statuses))]

    async def admin_get_order(self, order_id: int) -> Optional[dict]:
        head = await self.db.fetchrow("""
                                      SELECT o.id,
                                             o.status,
                                             o.delivery_way,
                                             o.registration_date,
                                             o.delivery_date,
                                             o.finished_at,
                                             o.delivery_address,
                                             o.used_bonus,
                                             b.name_surname,
                                             b.tel_num,
                                             b.tg_username
                                      FROM buyer_orders o
                                               JOIN user_info u ON u.id = o.buyer_id
                                               JOIN buyer_info b ON b.user_id = u.id
                                      WHERE o.id = $1
                                      """, order_id)
        if not head:
            return None

        items = await self.db.fetch("""
                                    SELECT p.title, p.price, i.qty
                                    FROM order_items i
                                             JOIN product_position p ON p.id = i.position_id
                                    WHERE i.order_id = $1
                                    ORDER BY p.id
                                    """, order_id)

        total = sum(r["price"] * r["qty"] for r in items)
        data = dict(head)
        data["items"] = [dict(r) for r in items]
        data["total"] = int(total)
        return data

    async def mark_order_as_paid_by_bonus(self, order_id: int) -> bool:
        """
        Обновляет статус заказа на 'processing', если он был полностью оплачен бонусами.
        Возвращает True в случае успеха.
        """
        async with self.db.pool.acquire() as conn:
            # Обновляем статус и ставим дату "оплаты"
            result = await conn.execute(
                """
                UPDATE buyer_orders
                SET status = 'processing',
                    payment_date = CURRENT_TIMESTAMP
                WHERE id = $1 AND status = 'pending_payment'
                """,
                order_id
            )

            # result содержит строку "UPDATE N", где N - кол-во обновленных строк
            if 'UPDATE 1' in result:
                return True
            else:
                return False
