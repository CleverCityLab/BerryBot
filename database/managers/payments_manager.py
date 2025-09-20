from typing import Optional

from database.async_db import AsyncDatabase
from database.models.payments import PaymentStatus, Payment


class PaymentsManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def upsert_payment(
            self,
            *,
            tg_user_id: int,
            amount: float,
            yookassa_id: str,
            status: PaymentStatus,
            order_id: Optional[int],
    ) -> Payment:
        sql = """
              INSERT INTO payments (tg_user_id, amount, yookassa_id, status, order_id)
              VALUES ($1, $2::numeric, $3, $4::payment_status, $5)
              ON CONFLICT (yookassa_id) DO UPDATE
                  SET status     = EXCLUDED.status,
                      amount     = EXCLUDED.amount,
                      tg_user_id = EXCLUDED.tg_user_id,
                      order_id   = EXCLUDED.order_id
              RETURNING id, tg_user_id, amount, yookassa_id, status, order_id;
              """
        rec = await self.db.fetchrow(sql, tg_user_id, amount, yookassa_id, status.value, order_id)
        return Payment.from_record(rec)

    async def set_status_by_yk_id(self, yookassa_id: str, status: PaymentStatus) -> Optional[Payment]:
        sql = """
              UPDATE payments
              SET status = $2::payment_status
              WHERE yookassa_id = $1
              RETURNING id, tg_user_id, amount, yookassa_id, status, order_id;
              """
        rec = await self.db.fetchrow(sql, yookassa_id, status.value)
        return Payment.from_record(rec) if rec else None
