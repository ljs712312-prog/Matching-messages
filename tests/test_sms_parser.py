from sms_parser import parse_sms


def test_court_name_preprocess_removes_prefix_noise():
    text = """
010 3384 0999번수원 5월22일
25ㅡ888번 아파트
010 6833 1523번
"""
    rows = parse_sms(text)

    assert rows[0]["법원"] == "수원"
    assert rows[0]["사건번호"] == "2025타경888"
    assert rows[0]["전화번호"] == "010-6833-1523"
    assert rows[0]["법원"] != "번수원"


def test_court_name_preprocess_removes_free_text_before_court():
    text = """
금리저렴 찾고있슴수원 5월18일
23ㅡ13274 번 빌라 문자
1 2 3 4 5 6 12 13번
010 6219 7075번
"""
    rows = parse_sms(text)

    assert rows
    assert {row["물건번호"] for row in rows} == {"1", "2", "3", "4", "5", "6", "12", "13"}
    assert all(row["법원"] == "수원" for row in rows)
    assert all(row["사건번호"] == "2023타경13274" for row in rows)


def test_case_with_many_items_one_phone():
    text = """
수원 5월 15일

24ㅡ3700번 빌라사업자
2 3 4 5 10 12번 구자순
010 8575 4587번
"""
    rows = parse_sms(text)

    assert {row["물건번호"] for row in rows} == {"2", "3", "4", "5", "10", "12"}
    assert all(row["사건번호"] == "2024타경3700" for row in rows)
    assert all(row["물건정보"] == "빌라" for row in rows)
    assert all(row["전화번호"] == "010-8575-4587" for row in rows)
    assert all("빌라사업자" in row["비고"] and "구자순" in row["비고"] for row in rows)


def test_892_friend_items_are_not_dropped():
    text = """
25ㅡ892번 아공

1번 2번 3번 4번 5번6번
친구물건

7 8 9 10 11 12번 까지는
본인 010 4503 3333번
"""
    rows = parse_sms(text)
    by_item = {row["물건번호"]: row for row in rows}

    assert set(by_item) == {str(number) for number in range(1, 13)}
    for item in ["1", "2", "3", "4", "5", "6"]:
        assert by_item[item]["전화번호"] == ""
        assert "친구물건" in by_item[item]["비고"]
        assert "전화번호 미확인" in by_item[item]["확인필요사유"]
    for item in ["7", "8", "9", "10", "11", "12"]:
        assert by_item[item]["전화번호"] == "010-4503-3333"
        assert "본인" in by_item[item]["비고"]


def test_case_with_multiple_buyers_and_following_remark():
    text = """
25ㅡ50994 3번 상가
010 4817 1577번

4번 010 6223 7465번
5번 010 3757 7512번

4번 5번 친구사이입니다
"""
    rows = parse_sms(text)
    by_item = {row["물건번호"]: row for row in rows}

    assert set(by_item) == {"3", "4", "5"}
    assert by_item["3"]["전화번호"] == "010-4817-1577"
    assert by_item["4"]["전화번호"] == "010-6223-7465"
    assert by_item["5"]["전화번호"] == "010-3757-7512"
    assert "친구사이" in by_item["4"]["비고"]
    assert "친구사이" in by_item["5"]["비고"]


def test_complex_sms_keeps_case_context():
    text = """
25ㅡ55465 빌라 문자
1 5 10번 3건
010 6219 7075번

2번 8번 1주택 투자
010 9461 1342번
"""
    rows = parse_sms(text)
    by_item = {row["물건번호"]: row for row in rows}

    for item in ["1", "5", "10"]:
        assert by_item[item]["전화번호"] == "010-6219-7075"
        assert by_item[item]["물건정보"] == "빌라"
        assert "문자" in by_item[item]["비고"]
        assert "3건" in by_item[item]["비고"]

    for item in ["2", "8"]:
        assert by_item[item]["전화번호"] == "010-9461-1342"
        assert by_item[item]["물건정보"] == "빌라"
        assert "1주택" in by_item[item]["비고"]
        assert "투자" in by_item[item]["비고"]


def test_full_case_number_and_comma_item_list():
    text = """
2025타경55465 빌라
1, 5, 10번 문자
010 6219 7075번
"""
    rows = parse_sms(text)
    by_item = {row["물건번호"]: row for row in rows}

    assert set(by_item) == {"1", "5", "10"}
    assert all(row["사건번호"] == "2025타경55465" for row in rows)
    assert all(row["전화번호"] == "010-6219-7075" for row in rows)


def test_multiple_cases_on_one_line_keep_each_property():
    text = "23ㅡ13410  8번 빌라  25ㅡ55143번  아파트  25ㅡ55424번  아파트 24ㅡ11480번  임야"

    rows = parse_sms(text)
    by_case = {row["사건번호"]: row for row in rows}

    assert set(by_case) == {"2023타경13410", "2025타경55143", "2025타경55424", "2024타경11480"}
    assert by_case["2023타경13410"]["물건번호"] == "8"
    assert by_case["2023타경13410"]["물건정보"] == "빌라"
    assert by_case["2025타경55143"]["물건번호"] == "1"
    assert by_case["2025타경55143"]["물건정보"] == "아파트"
    assert by_case["2025타경55424"]["물건번호"] == "1"
    assert by_case["2025타경55424"]["물건정보"] == "아파트"
    assert by_case["2024타경11480"]["물건번호"] == "1"
    assert by_case["2024타경11480"]["물건정보"] == "임야"


def test_55465_many_item_groups_stay_under_same_case():
    text = """
25ㅡ55465 빌라 문자
1 5 10번 3건
010 6219 7075번

2번 8번 1주택 투자
010 9461 1342번

4, 3, 6, 14, 7, 9번
010 1111 2222번
"""
    rows = parse_sms(text)
    by_item = {row["물건번호"]: row for row in rows}

    assert set(by_item) == {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "14"}
    assert all(row["사건번호"] == "2025타경55465" for row in rows)
    assert by_item["10"]["전화번호"] == "010-6219-7075"
    assert by_item["2"]["전화번호"] == "010-9461-1342"
    assert by_item["14"]["전화번호"] == "010-1111-2222"


def test_june_17_message_template_parses_all_cases():
    text = """수원 6월 17일
24ㅡ14090 2번 상가
대출많이 요구
010 6667 1625번
24ㅡ69267번 아파트
컨비 많이 요구함
010 7114 7780번
24ㅡ78269번 아파트
1주택 투자자
010 5006 2601번
24ㅡ86019번 오피 투자
010 7337 1275번
25ㅡ886번 빌라
1주택 카드만 사용
010 4117 1882번
25ㅡ1080번 아파트
1주택 8월말 처분 계약서
소득 1천7백 카드 2천5백
입주예정
010 4000 8700번
25ㅡ55203번 아파트
무주택 투자 소득4천
010 5508 0405번
25ㅡ55383번 빌라
입주 무주택 소득8천
010 5577 9199번"""

    rows = parse_sms(text)

    assert len(rows) == 8
    assert rows[0]["사건번호"] == "2024타경14090"
    assert rows[0]["물건번호"] == "2"
    assert rows[-1]["사건번호"] == "2025타경55383"
    assert all(row["날짜"] == "2026-06-17" for row in rows)
