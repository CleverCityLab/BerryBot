# database/managers/warehouse_manager.py

from typing import Optional, Dict, Any

from database.async_db import AsyncDatabase
from utils.logger import get_logger

log = get_logger("[WarehouseManager]")


class WarehouseManager:
    def __init__(self, db: AsyncDatabase):
        self.db = db

    async def get_default_warehouse(self) -> Optional[Dict[str, Any]]:
        """

        Возвращает информацию об активном складе, который помечен как is_default=TRUE.
        """
        sql = "SELECT * FROM warehouses WHERE is_default = TRUE AND is_active = TRUE LIMIT 1"
        record = await self.db.fetchrow(sql)
        return dict(record) if record else None

    async def update_field(self, warehouse_id: int, field_name: str, new_value: any):
        """
        Обновляет указанное текстовое поле для указанного склада.
        """
        # "Белый список" полей, которые администратор может изменять текстом.
        allowed_fields = ["name", "address", "contact_name", "contact_phone",
                          "porch", "floor", "apartment", "comment"]

        if field_name not in allowed_fields:
            log.warning(f"Попытка обновить запрещенное или неизвестное поле: {field_name}")
            return

        # Используем f-строку для имени поля, так как оно приходит из нашего же кода
        # и проверено по "белому списку".
        # Для значений от пользователя ($1, $2) всегда используем плейсхолдеры!
        sql = f'UPDATE warehouses SET "{field_name}" = $1 WHERE id = $2'
        await self.db.execute(sql, new_value, warehouse_id)

    async def update_location(self, warehouse_id: int, latitude: float, longitude: float):
        """
        Обновляет широту и долготу для указанного склада.
        """
        sql = "UPDATE warehouses SET latitude = $1, longitude = $2 WHERE id = $3"
        await self.db.execute(sql, latitude, longitude, warehouse_id)

    async def create_default_warehouse(self, data: dict) -> int:
        """
        Создает новую запись о складе со всеми деталями.
        """
        sql = """
              INSERT INTO warehouses (name, address, latitude, longitude,
                                      contact_name, contact_phone,
                                      porch, floor, apartment, is_default, comment)
              VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, TRUE, $10)
              RETURNING id \
              """
        return await self.db.fetchval(
            sql,
            data.get('name'), data.get('address'),
            data.get('latitude'), data.get('longitude'),
            data.get('contact_name'), data.get('contact_phone'),
            data.get('porch'), data.get('floor'), data.get('apartment'), data.get('comment'),
        )

    async def update_address_and_location(
            self, warehouse_id: int, address: str, latitude: float, longitude: float
    ):
        """
        Обновляет текстовый адрес и координаты для указанного склада.
        """
        sql = """
              UPDATE warehouses
              SET address   = $1,
                  latitude  = $2,
                  longitude = $3
              WHERE id = $4 \
              """
        await self.db.execute(sql, address, latitude, longitude, warehouse_id)
