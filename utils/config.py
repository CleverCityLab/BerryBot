import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_MIN_POOL_SIZE = int(os.getenv("DB_MIN_POOL_SIZE", "10"))
DB_MAX_POOL_SIZE = int(os.getenv("DB_MAX_POOL_SIZE", "100"))

YOOKASSA_SHOP_ID = int(os.getenv("YOOKASSA_SHOP_ID"))
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN")

TIMEZONE_OFFSET = int(os.getenv("TIMEZONE_OFFSET", "3"))
