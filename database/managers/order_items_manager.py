from database.async_db import AsyncDatabase


class OrderItemsManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db
