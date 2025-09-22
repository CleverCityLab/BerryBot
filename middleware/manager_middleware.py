from aiogram import BaseMiddleware, Bot

from database.async_db import AsyncDatabase
from database.managers.buyer_info_manager import BuyerInfoManager
from database.managers.buyer_order_manager import BuyerOrderManager
from database.managers.order_items_manager import OrderItemsManager
from database.managers.payments_manager import PaymentsManager
from database.managers.product_position_manager import ProductPositionManager
from database.managers.user_info_manager import UserInfoManager
from database.managers.warehouse_manager import WarehouseManager
from api.yandex_delivery import YandexDeliveryClient


class ManagerMiddleware(BaseMiddleware):
    def __init__(
            self,
            db: AsyncDatabase,
            buyer_info_manager: BuyerInfoManager,
            buyer_order_manager: BuyerOrderManager,
            product_position_manager: ProductPositionManager,
            user_info_manager: UserInfoManager,
            order_items_manager: OrderItemsManager,
            warehouse_manager: WarehouseManager,
            payments_manager: PaymentsManager,
            bot: Bot,
            yandex_delivery_client: YandexDeliveryClient,
    ):
        super().__init__()
        self.db = db
        self.buyer_info_manager = buyer_info_manager
        self.buyer_order_manager = buyer_order_manager
        self.product_position_manager = product_position_manager
        self.user_info_manager = user_info_manager
        self.order_items_manager = order_items_manager
        self.warehouse_manager = warehouse_manager
        self.payments_manager = payments_manager
        self.bot = bot
        self.yandex_delivery_client = yandex_delivery_client

    async def __call__(self, handler, event, data):
        data["db"] = self.db
        data["buyer_info_manager"] = self.buyer_info_manager
        data["buyer_order_manager"] = self.buyer_order_manager
        data["product_position_manager"] = self.product_position_manager
        data["user_info_manager"] = self.user_info_manager
        data["order_items_manager"] = self.order_items_manager
        data["warehouse_manager"] = self.warehouse_manager
        data["payments_manager"] = self.payments_manager
        data["bot"] = self.bot
        data["yandex_delivery_client"] = self.yandex_delivery_client

        return await handler(event, data)
