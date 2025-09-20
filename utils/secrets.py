# utils/secrets.py
import os
import json
import logging
from threading import Lock

# Создаем Lock для безопасности при одновременной записи в файл
file_lock = Lock()
log = logging.getLogger(__name__)

SECRETS_JSON_PATH = os.path.join(os.path.dirname(__file__), '../secrets.json')

def _load_secrets() -> dict:
    try:
        with open(SECRETS_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Если файл не найден или пуст, возвращаем пустую структуру
        return {"ADMIN_IDS": []}

def _save_secrets(data: dict) -> None:
    with open(SECRETS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_admin_ids() -> list[int]:
    with file_lock:
        secrets = _load_secrets()
        # Убедимся, что возвращаем список целых чисел
        return [int(admin_id) for admin_id in secrets.get('ADMIN_IDS', [])]

def add_admin_id(user_id: int) -> bool:
    """Добавляет ID нового администратора. Возвращает True, если ID был добавлен."""
    with file_lock:
        secrets = _load_secrets()
        admin_ids = secrets.get('ADMIN_IDS', [])
        if user_id not in admin_ids:
            admin_ids.append(user_id)
            secrets['ADMIN_IDS'] = admin_ids
            _save_secrets(secrets)
            log.info(f"Администратор с ID {user_id} был добавлен.")
            return True
        log.warning(f"Попытка добавить существующего администратора с ID {user_id}.")
        return False

def remove_admin_id(user_id: int) -> bool:
    """Удаляет ID администратора. Возвращает True, если ID был удален."""
    with file_lock:
        secrets = _load_secrets()
        admin_ids = secrets.get('ADMIN_IDS', [])
        if user_id in admin_ids:
            admin_ids.remove(user_id)
            secrets['ADMIN_IDS'] = admin_ids
            _save_secrets(secrets)
            log.info(f"Администратор с ID {user_id} был удален.")
            return True
        log.warning(f"Попытка удалить несуществующего администратора с ID {user_id}.")
        return False