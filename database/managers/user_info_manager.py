from database.async_db import AsyncDatabase


class UserInfoManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db
