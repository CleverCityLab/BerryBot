import os
import json

SECRETS_JSON_PATH = os.path.join(os.path.dirname(__file__), '../secrets.json')


def _load_secrets() -> dict:
    with open(SECRETS_JSON_PATH, encoding='utf-8') as f:
        return json.load(f)


def _save_secrets(data: dict) -> None:
    with open(SECRETS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_admin_ids() -> list:
    return _load_secrets().get('ADMIN_IDS', [])
