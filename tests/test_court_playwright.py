from court_playwright import (
    _extract_distribution_items_from_page,
    _extract_items_from_case_text,
    _normalize_court,
    lookup_auction_items,
    _has_expected_items,
    _lookup_auction_items_parallel,
)
from sms_parser import FINAL_COLUMNS


def _row(**kwargs):
    row = {column: "" for column in FINAL_COLUMNS}
    row.update(
        {
            "법원": "수원",
            "사건번호": "2024타경3700",
            "물건번호": "1",
            "물건정보": "빌라",
            "전화번호": "010-1111-2222",
        }
    )
    row.update(kwargs)
    return row


def test_lookup_disabled_marks_status_and_reports_progress():
    progress = []

    rows = lookup_auction_items(
        [_row(사건번호="2099타경111111", 물건번호="91")],
        progress_callback=lambda done, total, message: progress.append((done, total, message)),
    )

    assert rows[0]["조회상태"] == "주소조회 미실행"
    assert rows[0]["확인필요사유"] == ""
    assert progress[-1] == (1, 1, "주소/호수 조회 완료")


def test_dirty_court_name_is_normalized_for_court_site():
    assert _normalize_court("번수원") == "수원지방법원"
    assert _normalize_court("찾고있슴수원") == "수원지방법원"
    assert _normalize_court("수원") == "수원지방법원"


def test_result_wait_requires_all_requested_items():
    items = {"1": {"전체주소": "주소1"}, "2": {"전체주소": "주소2"}}

    assert _has_expected_items(items, ["1", "2"])
    assert not _has_expected_items(items, ["1", "2", "3"])


def test_parallel_lookup_preserves_original_row_order(monkeypatch):
    monkeypatch.setattr("court_playwright.init_db", lambda: None)

    def fake_sequential(rows, progress_callback=None, lookup_enabled=None):
        output = []
        for done, row in enumerate(rows, start=1):
            result = dict(row)
            result["조회상태"] = f"완료-{row['사건번호']}"
            output.append(result)
            if progress_callback:
                progress_callback(done, len(rows), result["조회상태"])
        return output

    monkeypatch.setattr("court_playwright._lookup_auction_items_sequential", fake_sequential)
    rows = [
        _row(사건번호="2025타경3"),
        _row(사건번호="2025타경1"),
        _row(사건번호="2025타경2"),
    ]
    progress = []

    output = _lookup_auction_items_parallel(
        rows,
        lambda done, total, message: progress.append((done, total, message)),
        True,
        [[0], [1], [2]],
        2,
    )

    assert [row["사건번호"] for row in output] == ["2025타경3", "2025타경1", "2025타경2"]
    assert all(row["조회상태"].startswith("완료-") for row in output)
    assert progress[-1] == (3, 3, "주소/호수 조회 완료")


def test_lookup_normalizes_dirty_court_before_cache_lookup(monkeypatch):
    monkeypatch.setattr("court_playwright.init_db", lambda: None)
    monkeypatch.setattr("court_playwright.save_cached_item", lambda *args: None)

    def fake_cache(court, case_no, item_no):
        assert court == "수원"
        assert case_no == "2025타경55465"
        assert item_no == "1"
        return {
            "지번주소": "권선동 1022",
            "도로명주소": "경기도 수원시 권선구 권중로 110",
            "전체주소": "경기도 수원시 권선구 권중로 110",
        }

    monkeypatch.setattr("court_playwright.get_cached_item", fake_cache)

    rows = lookup_auction_items(
        [
            _row(
                법원="번수원",
                사건번호="2025타경55465",
                물건번호="1",
                조회상태="조회실패",
                확인필요사유="물건번호 미기재, 1번 추정 법원경매 조회 실패 법원 선택값을 찾지 못함: 번수원지방법원",
            )
        ],
        lookup_enabled=False,
    )

    assert rows[0]["법원"] == "수원"
    assert rows[0]["조회상태"] == "캐시"
    assert rows[0]["전체주소"] == "경기도 수원시 권선구 권중로 110"
    assert "물건번호 미기재" in rows[0]["확인필요사유"]
    assert "법원경매 조회 실패" not in rows[0]["확인필요사유"]


def test_lookup_parses_manually_entered_full_address(monkeypatch):
    monkeypatch.setattr("court_playwright.convert_to_jibun", lambda address: {})

    rows = lookup_auction_items(
        [
            _row(
                사건번호="2099타경222222",
                물건번호="92",
                전체주소="경기도 수원시 권선구 권선동 1022, ○○아파트 101동 1203호",
            )
        ]
    )

    assert rows[0]["조회상태"] == "주소파싱완료"
    assert rows[0]["지번주소"] == "권선동 1022"
    assert rows[0]["건물동"] == "101동"
    assert rows[0]["호수"] == "1203호"


def test_extract_items_from_court_case_text(monkeypatch):
    monkeypatch.setattr("court_playwright.convert_to_jibun", lambda address: {})
    text = """
물건내역
물건번호,물건용도,감정평가액,물건비고,물건상태,항고재항고,기일정보,최근입찰결과 을(를) 나타낸 표
물건번호
    1
물건용도
    상가,오피스텔
목록1,목록구분,비고,제시외 을(를) 나타낸 표
목록1
    경기도 수원시 권선구 경수대로 406, 3층301호 (권선동,파크앤시티타워2)
목록구분
    집합건물
물건상태
    매각준비
물건번호,물건용도,감정평가액,물건비고,물건상태,항고재항고,기일정보,최근입찰결과 을(를) 나타낸 표
물건번호
    2
물건용도
    아파트
목록1,목록구분,비고,제시외 을(를) 나타낸 표
목록2
    경기도 수원시 권선구 경수대로 406, 8층801호 (권선동,파크앤시티타워2)
목록구분
    집합건물
"""

    items = _extract_items_from_case_text(text)

    assert items["1"]["전체주소"] == "경기도 수원시 권선구 경수대로 406, 3층301호 (권선동,파크앤시티타워2)"
    assert items["1"]["지번주소"] == ""
    assert "지번주소 미확인" in items["1"]["확인필요사유"]
    assert items["1"]["건물명"] == "파크앤시티타워2"
    assert items["1"]["층"] == "3층"
    assert items["1"]["호수"] == "301호"
    assert items["2"]["호수"] == "801호"


def test_extract_items_without_repeated_table_header(monkeypatch):
    monkeypatch.setattr("court_playwright.convert_to_jibun", lambda address: {})
    text = """
물건내역
물건번호
  1
물건용도
  빌라
소재지
  경기도 수원시 팔달구 인계동 956-3 제3층 제301호
물건상태
  매각준비
물건번호
  2
물건용도
  빌라
도로명주소
  경기도 수원시 권선구 경수대로 406
목록1
  경기도 수원시 권선구 경수대로 406, 8층801호 (권선동,파크앤시티타워2)
목록구분
  집합건물
"""

    items = _extract_items_from_case_text(text)

    assert set(items) == {"1", "2"}
    assert items["1"]["지번주소"] == "인계동 956-3"
    assert items["1"]["층"] == "3층"
    assert items["1"]["호수"] == "301호"
    assert items["2"]["도로명주소"] == "경기도 수원시 권선구 경수대로 406"
    assert items["2"]["호수"] == "801호"


def test_extract_distribution_grid_items(monkeypatch):
    monkeypatch.setattr("court_playwright.convert_to_jibun", lambda address: {})

    class Page:
        def evaluate(self, script, arg):
            if isinstance(arg, dict):
                return [
                    {
                        "column1": "1",
                        "column3": "경기도 화성시 오산동 1047 동탄2신도시금강펜테리움센트럴파크, 1829동 9층901호",
                    },
                    {
                        "column1": "2",
                        "column3": "경기도 화성시 오산동 1047 동탄2신도시금강펜테리움센트럴파크, 1829동 9층902호",
                    },
                ]
            return 2

        def locator(self, selector):
            raise AssertionError("DOM fallback should not be used")

    items = _extract_distribution_items_from_page(Page())

    assert set(items) == {"1", "2"}
    assert items["1"]["지번주소"] == "오산동 1047"
    assert items["1"]["층"] == "9층"
    assert items["1"]["호수"] == "901호"
