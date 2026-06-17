from __future__ import annotations


def has_address_conversion_credentials() -> bool:
    return False


def address_conversion_status() -> str:
    return "사용 안 함"


def convert_to_jibun(address: str) -> dict:
    """External road-to-jibun conversion is intentionally disabled."""
    return {}
