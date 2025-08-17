from database.async_db import AsyncDatabase


class PaymentsManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db
