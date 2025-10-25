import json
import uuid
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

        if response_data and "price" in response_data:
            return float(response_data["price"])

        log.warning(f"Не удалось получить стоимость доставки для адреса: {client_address}. Ответ API: {response_data}")
        return None

    async def get_claim_info(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает полную, актуальную информацию по существующей заявке.
        (метод /b2b/cargo/integration/v2/claims/info)
        """
        path = "/b2b/cargo/integration/v2/claims/info"
        params = {"claim_id": claim_id}

        # Этот эндпоинт использует POST с query-параметрами, без тела
        response_data = await self._make_request("POST", path, params=params, json_payload={})

        if response_data and "id" in response_data:
            log.info(f"Получена информация для заявки {claim_id}. Статус: {response_data.get('status')}")
            return response_data

        log.warning(f"Не удалось получить информацию для заявки {claim_id}. Ответ: {response_data}")
        return None

    async def create_claim(
            self,
            items: List[Dict[str, Any]],  # Ожидаем ПОЛНЫЙ список товаров
            client_info: Dict[str, Any],  # Ожидаем ПОЛНЫЙ словарь клиента
            warehouse_info: Dict[str, Any],
            order_id: int,
            order_comment: Optional[str] = None
    ) -> Optional[str]:
        """
        Создаёт черновик заявки на доставку (/b2b/cargo/integration/v2/claims/create).
        Структура payload строго соответствует документации.
        """
        path = "/b2b/cargo/integration/v2/claims/create"

        # --- 1. Геокодируем адрес клиента, если нет координат ---
        if "latitude" not in client_info or "longitude" not in client_info:
            coords = await geocode_address(client_info["address"])
            if not coords:
                log.error(f"Не удалось найти координаты для адреса: {client_info['address']}")
                return None
            client_info["longitude"], client_info["latitude"] = coords

        # --- 2. Собираем объект адреса для Точки А (Склад) ---
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

        # --- 3. Собираем объект адреса для Точки Б (Клиент) ---
        destination_address = {
            "fullname": client_info["address"],
            "coordinates": [client_info["longitude"], client_info["latitude"]]
        }
        if client_info.get("porch"):
            destination_address["porch"] = client_info["porch"]
        if client_info.get("floor"):
            destination_address["sfloor"] = client_info["floor"]
        if client_info.get("apartment"):
            destination_address["sflat"] = client_info["apartment"]

        base_comment = f"Доставка заказа #{order_id} из Telegram-бота."
        full_comment = f"Комментарии: {order_comment}. {base_comment}" if order_comment else base_comment

        # --- 4. Формируем финальный, правильный payload ---
        payload = {
            "items": items,
            "route_points": [
                {
                    "point_id": 1,
                    "visit_order": 1,
                    "type": "source",
                    "address": source_address,
                    "contact": {
                        "name": warehouse_info["contact_name"],
                        "phone": warehouse_info["contact_phone"],
                    },
                },
                {
                    "point_id": 2,
                    "visit_order": 2,
                    "type": "destination",
                    "address": destination_address,
                    "contact": {
                        "name": client_info["name"],
                        "phone": client_info["phone"]
                    },
                    "external_order_id": str(order_id),
                },
            ],
            "client_requirements": {"taxi_class": "express"},
            # Добавляем другие полезные поля, как в продвинутой версии
            "comment": full_comment,
        }

        # Добавляем request_id как query-параметр, а не в тело
        params = {"request_id": str(uuid.uuid4())}

        log.debug(f"Отправка payload в {path}: {json.dumps(payload, indent=2, default=decimal_default_serializer)}")
        response_data = await self._make_request("POST", path, json_payload=payload, params=params)

        if response_data and "id" in response_data:
            return response_data["id"]

        log.error(f"Не удалось создать заявку для заказа #{order_id}. Ответ API: {response_data}")
        return None

    async def accept_claim(self, claim_id: str, version: int = 1) -> Optional[Dict[str, Any]]:
        """
        Подтверждает заявку (v2 API), запускает поиск курьера.
        В случае успеха возвращает ответ от API с новым статусом заявки.
        """
        path = "/b2b/cargo/integration/v2/claims/accept"
        payload = {"version": version}
        params = {"claim_id": claim_id}

        response_data = await self._make_request(
            "POST", path, json_payload=payload, params=params
        )

        if response_data and "id" in response_data:
            log.info(f"Заявка {claim_id} успешно подтверждена. Новый статус: {response_data.get('status')}")
            return response_data  # <-- Возвращаем весь ответ

        log.error(f"Ошибка подтверждения заявки {claim_id}. Ответ: {response_data}")
        return None

    async def get_courier_phone(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает номер телефона и добавочный для звонка курьеру.
        (метод /driver-voiceforwarding)
        """
        path = "/b2b/cargo/integration/v2/driver-voiceforwarding"
        payload = {"claim_id": claim_id}

        # Этот эндпоинт использует POST с телом запроса
        response_data = await self._make_request("POST", path, json_payload=payload)

        if response_data and "phone" in response_data:
            log.info(f"Получен телефон курьера для заявки {claim_id}: {response_data['phone']}")
            return response_data  # Возвращаем весь словарь {'phone': '...', 'ext': '...', 'ttl_seconds': ...}

        log.warning(f"Не удалось получить телефон курьера для заявки {claim_id}. Ответ: {response_data}")
        return None

    async def get_points_eta(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает точки маршрута и прогнозируемое время прибытия (ETA).
        (метод /claims/points-eta)
        """
        path = "/b2b/cargo/integration/v2/claims/points-eta"
        params = {"claim_id": claim_id}

        # Этот эндпоинт использует POST с query-параметрами, без тела запроса
        response_data = await self._make_request("POST", path, params=params, json_payload={})

        if response_data and "route_points" in response_data:
            log.info(f"Получен ETA для заявки {claim_id}.")
            return response_data  # Возвращаем полный ответ со всеми точками

        log.warning(f"Не удалось получить ETA для заявки {claim_id}. Ответ: {response_data}")
        return None

    async def get_tracking_links(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает ссылки для отслеживания курьера.
        (метод /claims/tracking-links)
        """
        path = "/b2b/cargo/integration/v2/claims/tracking-links"
        params = {"claim_id": claim_id}

        # Этот эндпоинт использует GET с query-параметрами
        response_data = await self._make_request("GET", path, params=params)  # Используем GET

        if response_data and "route_points" in response_data:
            log.info(f"Получены ссылки для отслеживания для заявки {claim_id}.")
            return response_data

        log.warning(f"Не удалось получить ссылки для отслеживания для заявки {claim_id}. Ответ: {response_data}")
        return None

    async def get_cancellation_info(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        5. Узнаёт условия отмены заявки (метод /claims/cancel-info).
        """
        path = "/b2b/cargo/integration/v2/claims/cancel-info"
        params = {"claim_id": claim_id}

        response_data = await self._make_request("POST", path, params=params, json_payload={})

        # --- ИСПРАВЛЕНИЕ: Проверяем поле 'cancel_state' ---
        if response_data and "cancel_state" in response_data:
            state = response_data['cancel_state']
            log.info(f"Получена информация об отмене для заявки {claim_id}. Статус отмены: {state}")
            return response_data

        log.warning(f"Не удалось получить информацию об отмене для {claim_id}. Ответ: {response_data}")
        return None

    async def cancel_claim(self, claim_id: str, cancel_state: str, version: int = 1) -> bool:
        """
        6. Отменяет заявку (метод /claims/cancel).
        Требует указания типа отмены (free/paid) и версии заявки.
        """
        path = "/b2b/cargo/integration/v2/claims/cancel"
        params = {"claim_id": claim_id}

        # --- ИСПРАВЛЕНИЕ: Формируем тело запроса ---
        payload = {
            "version": version,
            "cancel_state": cancel_state
        }

        response_data = await self._make_request("POST", path, params=params, json_payload=payload)

        # Успешный ответ содержит новый статус
        if response_data and "status" in response_data:
            new_status = response_data.get("status")
            log.info(f"Заявка {claim_id} успешно отменена. Новый статус: {new_status}")
            return True

        log.error(f"Ошибка отмены заявки {claim_id}. Ответ: {response_data}")
        return False
