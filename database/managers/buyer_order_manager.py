from database.async_db import AsyncDatabase


class BuyerOrderManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db
