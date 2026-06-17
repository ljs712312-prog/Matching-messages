from __future__ import annotations

import base64
import html
import random
import re
import shutil
import time
from collections import defaultdict
from collections.abc import Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from address_parser import parse_address
from cache_db import get_cached_item, init_db, save_cached_item
from config import HEADLESS, LOOKUP_DELAY_MAX, LOOKUP_DELAY_MIN, LOOKUP_ENABLED, OUTPUT_DIR
from address_converter import convert_to_jibun
from sms_parser import FINAL_COLUMNS


ProgressCallback = Callable[[int, int, str], None]

CASE_SEARCH_URL = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml"
COURT_SELECT = "#mf_wfm_mainFrame_sbx_auctnCsSrchCortOfc"
YEAR_SELECT = "#mf_wfm_mainFrame_sbx_auctnCsSrchCsYear"
CASE_NO_INPUT = "#mf_wfm_mainFrame_ibx_auctnCsSrchCsNo"
SEARCH_BUTTON = "#mf_wfm_mainFrame_btn_auctnCsSrchBtn"

_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def lookup_auction_items(
    rows: list[dict],
    progress_callback: ProgressCallback | None = None,
    lookup_enabled: bool | None = None,
) -> list[dict]:
    """
    법원경매정보 경매사건검색 화면에서 사건번호 단위로 조회해
    물건번호별 지번주소/도로명주소/건물동/층/호수를 채운다.
    """
    init_db()
    enabled = LOOKUP_ENABLED if lookup_enabled is None else lookup_enabled
    output_rows = [{column: row.get(column, "") for column in FINAL_COLUMNS} for row in rows]
    total = max(len(output_rows), 1)
    completed = 0
    _emit_progress(progress_callback, completed, total, "주소/호수 조회 준비 중")

    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(output_rows):
        court_label = _normalize_court_label(str(row.get("법원", "")).strip())
        row["법원"] = court_label
        grouped[(court_label, str(row.get("사건번호", "")).strip())].append(index)

    browser = None
    context = None
    page = None
    playwright = None
    try:
        for (court, case_no), indexes in grouped.items():
            if not case_no:
                for index in indexes:
                    _mark_failure(output_rows[index], "조회실패", "사건번호 없음")
                    completed += 1
                    _emit_progress(progress_callback, completed, total, f"{completed}/{total}행 처리 완료")
                continue

            pending_indexes: list[int] = []
            for index in indexes:
                row = output_rows[index]
                _clear_previous_lookup_failure(row)
                item_no = str(row.get("물건번호", "")).strip()

                if row.get("전체주소") or row.get("도로명주소") or row.get("지번주소"):
                    _fill_from_existing_address(row)
                    row["조회상태"] = "주소파싱완료"
                    save_cached_item(court, case_no, item_no, row)
                    completed += 1
                    _emit_progress(progress_callback, completed, total, f"{case_no} {item_no}번 주소 파싱 완료")
                    continue

                cached = get_cached_item(court, case_no, item_no)
                if cached:
                    _apply_cached(row, cached)
                    if (row.get("전체주소") or row.get("도로명주소")) and not row.get("지번주소"):
                        _fill_from_full_address(row)
                        save_cached_item(court, case_no, item_no, row)
                    completed += 1
                    _emit_progress(progress_callback, completed, total, f"{case_no} {item_no}번 캐시 사용")
                    continue

                pending_indexes.append(index)

            if not pending_indexes:
                continue

            if not enabled:
                for index in pending_indexes:
                    output_rows[index]["조회상태"] = "주소조회 미실행"
                    completed += 1
                    _emit_progress(progress_callback, completed, total, f"{case_no} 조회 비활성")
                continue

            if page is None:
                playwright = sync_playwright().start()
                browser = _launch_chromium(playwright)
                context = browser.new_context(
                    locale="ko-KR",
                    viewport={"width": 1400, "height": 1100},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/148.0.0.0 Safari/537.36"
                    ),
                )
                context.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "font", "media"}
                    else route.continue_(),
                )
                page = context.new_page()

            _emit_progress(progress_callback, completed, total, f"{case_no} 법원경매정보 조회 중")
            try:
                result_map = _lookup_case(page, court, case_no)
            except Exception as exc:
                _write_debug_files_from_page(page, case_no, f"조회 실패: {exc}")
                for index in pending_indexes:
                    _mark_failure(output_rows[index], "조회실패", str(exc))
                    completed += 1
                    _emit_progress(progress_callback, completed, total, f"{case_no} 조회 실패")
                continue

            for index in pending_indexes:
                row = output_rows[index]
                item_no = str(row.get("물건번호", "")).strip()
                data = result_map.get(item_no)
                if not data:
                    _mark_failure(row, "조회실패", f"물건번호 매칭 실패 {case_no} {item_no}번 주소를 찾지 못함")
                else:
                    _apply_address_data(row, data)
                    row["조회상태"] = "조회완료"
                    save_cached_item(court, case_no, item_no, row)
                completed += 1
                _emit_progress(progress_callback, completed, total, f"{case_no} {item_no}번 처리 완료")
    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()

    _emit_progress(progress_callback, total, total, "주소/호수 조회 완료")
    return output_rows


def _launch_chromium(playwright):
    executable_path = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
    )
    if executable_path:
        return playwright.chromium.launch(headless=HEADLESS, executable_path=executable_path)
    return playwright.chromium.launch(headless=HEADLESS)


def _lookup_case(page: Page, court: str, case_no: str) -> dict[str, dict]:
    year, number = _split_case_no(case_no)
    court_name = _normalize_court(court)

    page.goto(CASE_SEARCH_URL, wait_until="networkidle", timeout=60_000)
    page.wait_for_selector(COURT_SELECT, timeout=30_000)
    _select_option_by_text(page, COURT_SELECT, court_name)
    page.select_option(YEAR_SELECT, value=year)
    page.fill(CASE_NO_INPUT, number)
    _polite_delay()

    body_text = _submit_search_and_wait(page, case_no)
    items = _extract_items_from_case_page(page, body_text)
    if not items:
        if "해당 사건번호는 잘못된 번호입니다" in body_text:
            raise RuntimeError(f"{court_name} {case_no} 검색 결과 없음")
        raise RuntimeError(f"{court_name} {case_no} 물건별 주소 파싱 실패")
    return items


def _submit_search_and_wait(page: Page, case_no: str) -> str:
    last_text = ""
    for attempt in range(2):
        if attempt == 0:
            page.click(SEARCH_BUTTON)
        else:
            page.locator(CASE_NO_INPUT).press("Enter")

        last_text = _wait_for_result_text(page, case_no=case_no, timeout_seconds=45)
        if _case_result_ready(page, last_text, case_no):
            return last_text
    return last_text


def _wait_for_result_text(page: Page, case_no: str, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_text = ""
    while time.monotonic() < deadline:
        try:
            page.wait_for_load_state("networkidle", timeout=3_000)
        except PlaywrightTimeoutError:
            pass
        try:
            last_text = _clean_text(page.locator("body").inner_text(timeout=5_000))
        except PlaywrightTimeoutError:
            page.wait_for_timeout(1_000)
            continue
        if _case_result_ready(page, last_text, case_no):
            return last_text
        page.wait_for_timeout(1_000)
    return last_text


def _case_result_ready(page: Page, body_text: str, case_no: str) -> bool:
    if case_no not in body_text:
        return False
    if _websquare_grid_row_count(page, "mf_wfm_mainFrame_grd_dstrtDemnDts") > 0:
        return True
    if _websquare_grid_row_count(page, "mf_wfm_mainFrame_grd_gdsDts") > 0:
        return True
    if _websquare_grid_row_count(page, "mf_wfm_mainFrame_grd_lstDts") > 0:
        return True
    if "사건기본내역" in body_text and "등록된 물건내역이 없습니다" not in body_text:
        return True
    return False


def _extract_items_from_case_page(page: Page, body_text: str) -> dict[str, dict]:
    items = _extract_items_from_case_text(body_text)
    for item_no, data in _extract_distribution_items_from_page(page).items():
        items.setdefault(item_no, data)
    return items


def _extract_items_from_case_text(body_text: str) -> dict[str, dict]:
    text = _clean_text(body_text)
    if "물건내역" in text:
        text = text.split("물건내역", 1)[1]

    result: dict[str, dict] = {}
    for item_no, block in _iter_item_blocks(text):
        full_address, road_address = _extract_address_pair(block)
        if not full_address:
            continue

        result[item_no] = _build_address_data(full_address, road_address)
    return result


def _extract_distribution_items_from_page(page: Page) -> dict[str, dict]:
    rows = _websquare_grid_rows(
        page,
        "mf_wfm_mainFrame_grd_dstrtDemnDts",
        ["column1", "column3", "column4"],
    )
    if not rows:
        rows = _dom_grid_rows(page, "mf_wfm_mainFrame_grd_dstrtDemnDts")

    result: dict[str, dict] = {}
    for row in rows:
        item_no = _normalize_item_no(row.get("column1") or row.get("0") or "")
        address = _clean_address(str(row.get("column3") or row.get("1") or ""))
        if not item_no or not _looks_like_address(address):
            continue
        result[item_no] = _build_address_data(address)
    return result


def _websquare_grid_row_count(page: Page, grid_id: str) -> int:
    try:
        count = page.evaluate(
            """
            (gridId) => {
                const grid = window[gridId];
                if (!grid) return 0;
                const methods = ["getRowCount", "getTotalRow", "getDataLength", "getRealRowCount"];
                for (const method of methods) {
                    if (typeof grid[method] === "function") {
                        const value = Number(grid[method]());
                        if (Number.isFinite(value) && value > 0) return value;
                    }
                }
                return 0;
            }
            """,
            grid_id,
        )
        if int(count or 0) > 0:
            return int(count)
    except Exception:
        pass

    try:
        return page.locator(f"#{grid_id}_body_tbody tr").count()
    except Exception:
        return 0


def _websquare_grid_rows(page: Page, grid_id: str, column_ids: list[str]) -> list[dict[str, str]]:
    try:
        rows = page.evaluate(
            """
            ({ gridId, columnIds }) => {
                const grid = window[gridId];
                if (!grid) return [];

                const call = (method, args) => {
                    try {
                        if (typeof grid[method] === "function") {
                            const value = grid[method](...args);
                            return value == null ? "" : String(value).trim();
                        }
                    } catch (error) {}
                    return "";
                };

                let rowCount = 0;
                for (const method of ["getRowCount", "getTotalRow", "getDataLength", "getRealRowCount"]) {
                    const value = Number(call(method, []));
                    if (Number.isFinite(value) && value > 0) {
                        rowCount = value;
                        break;
                    }
                }

                const rows = [];
                for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
                    const row = {};
                    for (const columnId of columnIds) {
                        row[columnId] =
                            call("getCellData", [rowIndex, columnId]) ||
                            call("getCellDisplayValue", [rowIndex, columnId]) ||
                            call("getCellValue", [rowIndex, columnId]);
                    }
                    rows.push(row);
                }
                return rows;
            }
            """,
            {"gridId": grid_id, "columnIds": column_ids},
        )
    except Exception:
        return []

    if not isinstance(rows, list):
        return []
    return [{str(key): str(value or "") for key, value in row.items()} for row in rows if isinstance(row, dict)]


def _dom_grid_rows(page: Page, grid_id: str) -> list[dict[str, str]]:
    try:
        locator = page.locator(f"#{grid_id}_body_tbody tr")
        row_count = locator.count()
    except Exception:
        return []

    rows: list[dict[str, str]] = []
    for row_index in range(row_count):
        try:
            values = locator.nth(row_index).locator("td").all_inner_texts()
        except Exception:
            continue
        rows.append({str(index): _clean_text(value) for index, value in enumerate(values)})
    return rows


def _normalize_item_no(value: str) -> str:
    match = re.search(r"\d{1,4}", str(value or ""))
    return str(int(match.group(0))) if match else ""


def _iter_item_blocks(text: str) -> list[tuple[str, str]]:
    markers = list(re.finditer(r"물건번호\s+(\d{1,4})\s+물건용도", text))
    blocks: list[tuple[str, str]] = []
    for index, marker in enumerate(markers):
        item_no = str(int(marker.group(1)))
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        blocks.append((item_no, text[start:end]))
    return blocks


def _extract_address_pair(block: str) -> tuple[str, str]:
    road_address = _first_valid_address(_field_values(block, ["도로명주소"]))
    jibun_or_full = _first_valid_address(_field_values(block, ["소재지", "지번주소", "목록소재지"]))
    list_address = _first_valid_address(_list_address_values(block))
    full_address = jibun_or_full or list_address or road_address
    return full_address, road_address


def _field_values(block: str, labels: list[str]) -> list[str]:
    values: list[str] = []
    stop_labels = (
        r"도로명주소|소재지|지번주소|목록소재지|목록\d+|목록구분|비고|물건상태|감정평가액|"
        "물건번호|물건용도|제시외|기일정보|최근입찰결과"
    )
    for label in labels:
        pattern = rf"{label}\s+(.+?)(?=\s+(?:{stop_labels})(?:\s|,|$)|$)"
        values.extend(match.group(1) for match in re.finditer(pattern, block, re.DOTALL))
    return values


def _list_address_values(block: str) -> list[str]:
    values = []
    for match in re.finditer(r"목록\d+\s+(.+?)(?=\s+목록구분\b|\s+비고\b|\s+물건상태\b|\s+제시외\b|$)", block, re.DOTALL):
        values.append(match.group(1))
    return values


def _first_valid_address(values: list[str]) -> str:
    for value in values:
        address = _clean_address(value)
        if _looks_like_address(address):
            return address
    return ""


def _looks_like_address(value: str) -> bool:
    if not value or "," in value[:8]:
        return False
    return bool(re.search(r"[가-힣]+(?:시|도|군|구).*(?:동|리|읍|면|로|길)\s*\d", value))


def _build_address_data(full_address: str, road_address: str = "") -> dict:
    full_address = str(full_address or "").strip()
    road_address = str(road_address or "").strip()

    source_address = full_address or road_address
    parsed = _parse_address_compatible(source_address, road_address)

    converted = {}
    try:
        converted = convert_to_jibun(source_address)
    except Exception:
        converted = {}

    if converted.get("지번주소"):
        parsed["지번주소"] = converted["지번주소"]
    if converted.get("도로명주소") and not parsed.get("도로명주소"):
        parsed["도로명주소"] = converted["도로명주소"]

    parsed["전체주소"] = _best_full_address(parsed, full_address, road_address)

    reasons: list[str] = []
    if not parsed.get("지번주소"):
        reasons.append("지번주소 미확인")
    if not parsed.get("도로명주소"):
        reasons.append("도로명주소 미확인")

    parsed["확인필요사유"] = " ".join(dict.fromkeys(reasons))
    return parsed


def _parse_address_compatible(full_address: str, road_address: str = "") -> dict:
    full_address = str(full_address or "").strip()
    road_address = str(road_address or "").strip()

    try:
        parsed = parse_address(full_address, road_address)
    except TypeError:
        parsed = parse_address(full_address)
        if parsed.get("동주소") and not parsed.get("지번주소"):
            parsed["지번주소"] = parsed["동주소"]
        if parsed.get("동") and not parsed.get("건물동"):
            parsed["건물동"] = parsed["동"]
        if road_address and not parsed.get("도로명주소"):
            parsed["도로명주소"] = road_address
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    parsed.setdefault("지번주소", "")
    parsed.setdefault("도로명주소", road_address)
    parsed.setdefault("전체주소", full_address)
    parsed.setdefault("건물명", "")
    parsed.setdefault("건물동", "")
    parsed.setdefault("층", "")
    parsed.setdefault("호수", "")
    parsed.setdefault("확인필요사유", "")

    if parsed.get("동주소") and not parsed.get("지번주소"):
        parsed["지번주소"] = parsed["동주소"]
    if parsed.get("동") and not parsed.get("건물동"):
        parsed["건물동"] = parsed["동"]

    # 지번주소가 "권선동"처럼 동 이름만 들어간 경우 실패 처리
    jibun = str(parsed.get("지번주소", "") or "").strip()
    if jibun and not re.search(r"(동|리|읍|면)\s*\d", jibun):
        parsed["지번주소"] = ""

    # 예비 추출: 권선동 1022 / 인계동 956-3
    if not parsed.get("지번주소"):
        m = re.search(r"([가-힣]+동|[가-힣]+리|[가-힣]+읍|[가-힣]+면)\s*\d+(?:-\d+)?", full_address)
        if m:
            parsed["지번주소"] = m.group(0).strip()

    # 건물동 예비 추출: 101동 / 제101동 / A동 / 비동
    if not parsed.get("건물동"):
        m = re.search(r"(?:제\s*)?(\d{1,4}동|[A-Za-z가-힣]{1,5}동)", full_address)
        if m:
            candidate = m.group(1).replace("제", "").strip()
            # 권선동/인계동 같은 법정동은 건물동으로 넣지 않기
            if not re.search(r"(권선|인계|매탄|율전|망포|우만|고등|영화|조원|송죽|정자|연무|화서|세류|호매실|금곡|탑동|구운|평동|서둔|입북|당수|오목천|곡반정|이의|하동|원천|영통|신동|매교|교동|지동|남수|북수|장안|팔달|권선|영통)동$", candidate):
                parsed["건물동"] = candidate

    # 층 예비 추출
    if not parsed.get("층"):
        m = re.search(r"(?:제\s*)?(\d{1,2})층", full_address)
        if m:
            parsed["층"] = f"{m.group(1)}층"

    # 호수 예비 추출
    if not parsed.get("호수"):
        m = re.search(r"(?:제\s*)?(\d{2,5})호", full_address)
        if m:
            parsed["호수"] = f"{m.group(1)}호"

    return parsed


def _fill_from_existing_address(row: dict) -> None:
    full_address = str(row.get("전체주소") or row.get("지번주소") or row.get("도로명주소") or "")
    data = _build_address_data(full_address, str(row.get("도로명주소", "")))
    _apply_address_data(row, data)


def _fill_from_full_address(row: dict) -> None:
    """
    캐시 또는 기존 row에 전체주소/도로명주소가 있는데 지번주소가 비어 있을 때
    주소 파싱을 다시 실행해서 지번주소/도로명주소/건물동/층/호수를 채운다.
    기존 코드에서 호출만 있고 정의가 빠져 있었던 함수.
    """
    full_address = str(row.get("전체주소") or row.get("지번주소") or row.get("도로명주소") or "").strip()
    road_address = str(row.get("도로명주소") or "").strip()

    if not full_address and not road_address:
        _append_reason(row, "주소 없음")
        return

    try:
        data = _build_address_data(full_address or road_address, road_address)
        _apply_address_data(row, data)
    except Exception as exc:
        _append_reason(row, f"주소 파싱 실패 {exc}")


def _apply_cached(row: dict, cached: dict) -> None:
    for key in ["지번주소", "도로명주소", "전체주소", "건물명", "건물동", "층", "호수"]:
        row[key] = cached.get(key, "")
    row["전체주소"] = _best_full_address(row)
    row["조회상태"] = "캐시"
    if cached.get("확인필요사유"):
        _append_reason(row, str(cached["확인필요사유"]))


def _apply_address_data(row: dict, data: dict) -> None:
    for key in ["지번주소", "도로명주소", "전체주소", "건물명", "건물동", "층", "호수"]:
        row[key] = data.get(key, "")
    row["전체주소"] = _best_full_address(row)
    if data.get("확인필요사유"):
        _append_reason(row, str(data["확인필요사유"]))


def _best_full_address(data: dict, full_address: str = "", road_address: str = "") -> str:
    return str(
        data.get("전체주소")
        or full_address
        or road_address
        or data.get("도로명주소")
        or data.get("지번주소")
        or ""
    ).strip()


def _clear_previous_lookup_failure(row: dict) -> None:
    if row.get("조회상태") in {"조회실패", "주소조회 미실행"}:
        row["조회상태"] = ""

    reason = str(row.get("확인필요사유", "")).strip()
    for marker in ["법원경매 조회 실패", "물건번호 매칭 실패", "주소조회 미실행"]:
        if marker in reason:
            reason = reason.split(marker, 1)[0].strip()
    row["확인필요사유"] = reason


def _split_case_no(case_no: str) -> tuple[str, str]:
    match = re.search(r"(\d{4})\s*타경\s*(\d{1,7})", case_no)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"(\d{2})\D+(\d{1,7})", case_no)
    if match:
        return f"20{match.group(1)}", match.group(2)
    raise ValueError(f"사건번호 형식 확인 필요: {case_no}")


def _normalize_court(court: str) -> str:
    court = (court or "").strip()
    if not court or "수원" in court:
        return "수원지방법원"
    if court.endswith("지방법원") or court.endswith("지원"):
        return court
    if court:
        return f"{court}지방법원"
    return "수원지방법원"


def _normalize_court_label(court: str) -> str:
    court = (court or "").strip()
    if not court or "수원" in court:
        return "수원"
    if court.endswith("지방법원"):
        return court.removesuffix("지방법원")
    if court.endswith("법원"):
        return court.removesuffix("법원")
    return court


def _select_option_by_text(page: Page, selector: str, text: str) -> None:
    index = page.eval_on_selector(
        selector,
        """
        (el, text) => Array.from(el.options).findIndex(
            option => option.textContent.trim() === text || option.textContent.trim().includes(text)
        )
        """,
        text,
    )
    if index < 0:
        raise RuntimeError(f"법원 선택값을 찾지 못함: {text}")
    page.select_option(selector, index=index)


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", (value or "").replace("\xa0", " ")).strip()


def _clean_address(value: str) -> str:
    value = _clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \n\t,")


def _mark_failure(row: dict, status: str, reason: str) -> None:
    row["조회상태"] = status
    if status == "조회실패" and "법원경매 조회 실패" not in reason and "물건번호 매칭 실패" not in reason:
        reason = f"법원경매 조회 실패 {reason}"
    _append_reason(row, reason)


def _append_reason(row: dict, reason: str) -> None:
    current = str(row.get("확인필요사유", "")).strip()
    if reason and reason not in current:
        row["확인필요사유"] = f"{current} {reason}".strip()


def _emit_progress(progress_callback: ProgressCallback | None, completed: int, total: int, message: str) -> None:
    if progress_callback:
        progress_callback(completed, total, message)


def _polite_delay() -> None:
    time.sleep(random.uniform(LOOKUP_DELAY_MIN, LOOKUP_DELAY_MAX))


def _write_debug_files_from_page(page: Page, case_no: str, message: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_case_no = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", case_no)
    html_path = OUTPUT_DIR / f"debug_{safe_case_no}.html"
    png_path = OUTPUT_DIR / f"debug_{safe_case_no}.png"
    try:
        content = page.content()
    except Exception:
        content = f"<html><body>{html.escape(message)}</body></html>"
    html_path.write_text(content, encoding="utf-8")
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except (PlaywrightTimeoutError, Exception):
        png_path.write_bytes(_ONE_PIXEL_PNG)
