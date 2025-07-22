from database.async_db import AsyncDatabase


class BuyerInfoManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db
