from address_parser import parse_address


def test_apartment_address():
    result = parse_address(
        "경기도 수원시 권선구 권선동 1022 권선자이아파트 101동 1203호",
        "경기도 수원시 권선구 권중로 110",
    )

    assert result["지번주소"] == "권선동 1022"
    assert result["도로명주소"] == "경기도 수원시 권선구 권중로 110"
    assert result["건물동"] == "101동"
    assert result["호수"] == "1203호"


def test_villa_address_with_floor():
    result = parse_address("경기도 수원시 팔달구 인계동 956-3 제3층 제301호")

    assert result["지번주소"] == "인계동 956-3"
    assert result["층"] == "3층"
    assert result["호수"] == "301호"


def test_dong_only_is_not_jibun_address():
    result = parse_address("경기도 수원시 장안구 율전동")

    assert result["지번주소"] == ""
    assert "지번주소 미확인" in result["확인필요사유"]
