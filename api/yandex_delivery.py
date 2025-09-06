import json
from typing import List, Dict, Any, Optional
from decimal import Decimal

import aiohttp

from utils.logger import get_logger

log = get_logger("[YandexDeliveryAPI]")


def decimal_default_serializer(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


async def geocode_address(address: str) -> tuple[float, float] | None:
    """
    Преобразует адрес в координаты (lat, lon) через OpenStreetMap Nominatim API.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "MyDeliveryBot/1.0"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if not data:
                return None
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            return lon, lat  # ⚠️ Яндекс ждёт [lon, lat]


class YandexDeliveryClient:
    def __init__(self, token: str):
        self._base_url = "https://b2b.taxi.yandex.net"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Language": "ru",
        }
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(
                headers=self._headers,
                json_serialize=lambda obj: json.dumps(obj, default=decimal_default_serializer),
                connector=connector,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _make_request(
            self,
            method: str,
            path: str,
            json_payload: Optional[Dict] = None,
            params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        session = await self._get_session()
        url = self._base_url + path
        try:
            async with session.request(method, url, json=json_payload, params=params) as response:
                data = await response.json()
                if 200 <= response.status < 300:
                    log.debug(f"{method} {path} -> {response.status}")
                    return data
                else:
                    log.error(f"Ошибка API Яндекса ({response.status}) {method} {path}: {data}")
                    return None
        except Exception as e:
            log.exception(f"Исключение при {method} {path}: {e}")
            return None

    async def calculate_price(
            self,
            items: List[Dict[str, Any]],
            client_address: str,
            warehouse_info: Dict[str, Any],
            buyer_info: Dict[str, Any]
    ) -> Optional[float]:
        """
        Рассчитывает стоимость доставки (/check-price), передавая полную
        детализацию адреса и для ОТПРАВИТЕЛЯ, и для ПОЛУЧАТЕЛЯ.
        """
        path = "/b2b/cargo/integration/v2/check-price"

        # --- 1. Получаем координаты клиента ---
        coords = await geocode_address(client_address)
        if not coords:
            log.error(f"Не удалось геокодировать адрес клиента: {client_address}")
            return None
        client_lon, client_lat = coords

        # --- 2. Собираем объект адреса для ТОЧКИ А (Склад) ---
        source_address = {
            "fullname": warehouse_info["address"],
            "coordinates": [float(warehouse_info["longitude"]), float(warehouse_info["latitude"])]
        }
        # Добавляем детали склада, если они есть в базе
        if warehouse_info.get("porch"):
            source_address["porch"] = warehouse_info["porch"]
        if warehouse_info.get("floor"):
            source_address["sfloor"] = warehouse_info["floor"]
        if warehouse_info.get("apartment"):
            source_address["sflat"] = warehouse_info["apartment"]

        # --- 3. Собираем объект адреса для ТОЧКИ Б (Клиент) ---
        destination_address = {
            "fullname": client_address,
            "coordinates": [client_lon, client_lat]
        }
        # Добавляем детали клиента, если они есть в его профиле
        if buyer_info.get("porch"): destination_address["porch"] = buyer_info["porch"]
        if buyer_info.get("floor"): destination_address["sfloor"] = buyer_info["floor"]
        if buyer_info.get("apartment"): destination_address["sflat"] = buyer_info["apartment"]

        # --- 4. Формируем финальный payload ---
        payload = {
            "items": items,
            "route_points": [
                source_address,  # <-- Передаем детализированный адрес склада
                destination_address  # <-- Передаем детализированный адрес клиента
            ],
            "requirements": {"taxi_class": "express"},
        }

        log.debug(f"Отправка payload в {path}: {json.dumps(payload, indent=2, default=decimal_default_serializer)}")
        response_data = await self._make_request("POST", path, json_payload=payload)

        if response_data and "price" in response_data:
            return float(response_data["price"])

        log.warning(f"Не удалось получить стоимость доставки для адреса: {client_address}. Ответ API: {response_data}")
        return None

    async def create_claim(
            self,
            items: List[Dict[str, Any]],
            client_address: str,
            warehouse_info: Dict[str, Any],
            buyer_info: Dict[str, Any]
    ) -> Optional[str]:
        """
        Создаёт черновик заявки на доставку (v2 API), используя полную детализацию.
        Возвращает claim_id.
        """
        path = "/b2b/cargo/integration/v2/claims/create"

        # --- 1. Получаем координаты клиента ---
        coords = await geocode_address(client_address)
        if not coords:
            log.error(f"Не удалось найти координаты для адреса: {client_address} при создании заявки.")
            return None
        client_lon, client_lat = coords

        # --- 2. Собираем объект адреса для ТОЧКИ А (Склад) ---
        source_address = {
            "fullname": warehouse_info["address"],
            "coordinates": [float(warehouse_info["longitude"]), float(warehouse_info["latitude"])]
        }
        if warehouse_info.get("porch"):
            source_address["porch"] = warehouse_info["porch"]
        if warehouse_info.get("floor"):
            source_address["sfloor"] = warehouse_info["floor"]
        if warehouse_info.get("apartment"):
            source_address["sflat"] = warehouse_info["apartment"]

        # --- 3. Собираем объект адреса для ТОЧКИ Б (Клиент) ---
        destination_address = {
            "fullname": client_address,
            "coordinates": [client_lon, client_lat]
        }
        if buyer_info.get("porch"):
            destination_address["porch"] = buyer_info["porch"]
        if buyer_info.get("floor"):
            destination_address["sfloor"] = buyer_info["floor"]
        if buyer_info.get("apartment"):
            destination_address["sflat"] = buyer_info["apartment"]

        # --- 4. Формируем финальный payload ---
        payload = {
            "items": items,
            "route_points": [
                source_address,  # <-- Передаем детализированный адрес склада
                destination_address  # <-- Передаем детализированный адрес клиента
            ],
            "requirements": {"taxi_class": "express"},
        }

        log.debug(f"Отправка payload в {path}: {json.dumps(payload, indent=2, default=decimal_default_serializer)}")
        response_data = await self._make_request("POST", path, json_payload=payload)

        if response_data and "id" in response_data:
            claim_id = response_data["id"]
            log.info(f"Создан черновик заявки для заказа. Claim ID: {claim_id}")
            return claim_id

        log.error(f"Не удалось создать заявку для заказа. Ответ API: {response_data}")
        return None

    async def accept_claim(self, claim_id: str, version: int = 1) -> bool:
        """
        Подтверждает заявку (v2 API), запускает поиск курьера.
        """
        path = "/b2b/cargo/integration/v2/claims/accept"
        payload = {"version": version}

        response_data = await self._make_request(
            "POST", path, json_payload=payload, params={"claim_id": claim_id}
        )

        if response_data is not None:
            log.info(f"Заявка {claim_id} подтверждена (версия {version}).")
            return True

        log.error(f"Ошибка подтверждения заявки {claim_id}.")
        return False
