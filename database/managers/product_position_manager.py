from database.async_db import AsyncDatabase

class ProductPositionManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db