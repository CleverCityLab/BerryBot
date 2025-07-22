from .admin import register_admin
from .client import register_client


def register_handlers(dp):
    register_admin(dp)
    register_client(dp)
