import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException


def normalize_phone(raw: str, default_region: str = "RU") -> str | None:
    """
    Приводит телефон к формату E.164 («+77771234567»).
    Возвращает None, если номер некорректный.
    """
    try:
        num = phonenumbers.parse(raw, default_region)
    except NumberParseException:
        return None

    if not phonenumbers.is_valid_number(num):
        return None

    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
