from address_converter import (
    address_conversion_status,
    convert_to_jibun,
    has_address_conversion_credentials,
)


def test_external_address_conversion_is_disabled():
    assert not has_address_conversion_credentials()
    assert address_conversion_status() == "사용 안 함"
    assert convert_to_jibun("경기도 수원시 권선구 경수대로 406") == {}
