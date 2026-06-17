from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


FINAL_COLUMNS = [
    "날짜",
    "법원",
    "사건번호",
    "물건번호",
    "물건정보",
    "지번주소",
    "도로명주소",
    "전체주소",
    "건물명",
    "건물동",
    "층",
    "호수",
    "전화번호",
    "비고",
    "조회상태",
    "확인필요사유",
]

CASE_RE = re.compile(
    r"(?<!\d)(?:(?P<year4>\d{4})\s*타\s*경\s*(?P<num4>\d{1,7})|"
    r"(?P<year2>\d{2})\s*[ㅡ\-–—－]\s*(?P<num2>\d{1,7}))(?:\s*번)?"
)
DATE_RE = re.compile(r"(?P<court>수원(?:지방법원)?)\s*(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일?")
PHONE_010_RE = re.compile(r"(?<!\d)(010)[\s\-]*(\d{3,4})[\s\-]*(\d{4})(?:\s*번)?")
PHONE_LOCAL_RE = re.compile(r"(?<!\d)(\d{3,4})[\s\-]+(\d{4})(?:\s*번)")
ITEM_LIST_RE = re.compile(r"(?<!\d)((?:\d{1,3}\s+){1,20}\d{1,3})\s*번")
ITEM_EXPLICIT_RE = re.compile(r"(?<!\d)(\d{1,3})\s*번")

PROPERTY_KEYWORDS = [
    "오피스텔",
    "근린주택",
    "아파트",
    "다가구",
    "빌라",
    "상가",
    "근린",
    "주택",
    "임야",
    "대지",
    "공장",
    "아공",
    "오피",
    "전",
]


@dataclass
class _Pending:
    items: list[str] = field(default_factory=list)
    phone: str = ""
    remarks: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.items.clear()
        self.phone = ""
        self.remarks.clear()
        self.reasons.clear()


def parse_sms(text: str, default_court: str = "수원", default_year: int = 2026) -> list[dict]:
    rows: list[dict] = []
    text = _preprocess_text(text)
    current_date = ""
    current_court = _normalize_court(default_court)
    current_case = ""
    current_property = ""
    case_remarks: list[str] = []
    pending = _Pending()
    last_row_indexes: list[int] = []

    def flush_pending() -> None:
        nonlocal last_row_indexes
        if not current_case:
            pending.clear()
            return
        if pending.items:
            reasons = list(pending.reasons)
            if not pending.phone:
                reasons.append("전화번호 미확인")
            last_row_indexes = _add_rows(
                rows,
                current_date,
                current_court,
                current_case,
                pending.items,
                [pending.phone] if pending.phone else [""],
                current_property,
                _merge_texts(case_remarks + pending.remarks),
                reasons,
            )
        elif pending.phone:
            last_row_indexes = _add_rows(
                rows,
                current_date,
                current_court,
                current_case,
                ["1"],
                [pending.phone],
                current_property,
                _merge_texts(case_remarks + pending.remarks),
                pending.reasons + ["물건번호 미기재, 1번 추정"],
            )
        elif not _case_has_rows(rows, current_case):
            reasons = list(pending.reasons)
            if not pending.phone:
                reasons.append("전화번호 미확인")
            reasons.append("물건번호 미기재, 1번 추정")
            last_row_indexes = _add_rows(
                rows,
                current_date,
                current_court,
                current_case,
                ["1"],
                [pending.phone] if pending.phone else [""],
                current_property,
                _merge_texts(case_remarks + pending.remarks),
                reasons,
            )
        pending.clear()

    for raw_line in text.splitlines():
        line = _normalize_space(raw_line)
        if not line:
            continue

        date_match = DATE_RE.search(line)
        if date_match:
            current_court = _normalize_court(date_match.group("court"))
            current_date = _format_date(default_year, int(date_match.group("month")), int(date_match.group("day")))

        case_matches = list(CASE_RE.finditer(line))
        if case_matches:
            flush_pending()
            case_match = case_matches[-1]
            current_case = _normalize_case_match(case_match)
            current_court = _normalize_court(current_court)
            current_property = ""
            case_remarks = []
            last_row_indexes = []

        line_property = _extract_property(line)
        if line_property:
            current_property = line_property

        phones = _extract_phones(line)
        phone_values = [phone for phone, _ in phones]
        phone_reasons = [reason for _, reason in phones if reason]
        items = _extract_item_numbers(line)
        line_remark = _extract_remark(line)

        if not current_case:
            continue

        if items and phone_values:
            if pending.items and not pending.phone:
                flush_pending()
            last_row_indexes = _add_rows(
                rows,
                current_date,
                current_court,
                current_case,
                items,
                phone_values,
                current_property,
                _merge_texts(case_remarks + [line_remark]),
                phone_reasons,
            )
            continue

        if items and not phone_values:
            existing_indexes = _find_row_indexes(rows, current_case, items)
            if existing_indexes and line_remark and not pending.items:
                _append_to_rows(rows, existing_indexes, "비고", line_remark)
                last_row_indexes = existing_indexes
            else:
                if pending.items and pending.items != items:
                    flush_pending()
                pending.items = items
                pending.remarks = [line_remark] if line_remark else []
                pending.reasons = []
            continue

        if phone_values and not items:
            if pending.items:
                last_row_indexes = _add_rows(
                    rows,
                    current_date,
                    current_court,
                    current_case,
                    pending.items,
                    phone_values,
                    current_property,
                    _merge_texts(case_remarks + pending.remarks + [line_remark]),
                    pending.reasons + phone_reasons,
                )
                pending.clear()
            else:
                pending.phone = phone_values[0]
                pending.remarks = [line_remark] if line_remark else []
                pending.reasons = phone_reasons
            continue

        if line_remark:
            if pending.items or pending.phone:
                pending.remarks.append(line_remark)
            elif last_row_indexes:
                _append_to_rows(rows, last_row_indexes, "비고", line_remark)
            else:
                case_remarks.append(line_remark)

    flush_pending()
    return _dedupe_rows(rows)


def _preprocess_text(text: str) -> str:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"(?<!^)(수원\s*\d{1,2}월\s*\d{1,2}일)", r"\n\1", value)
    value = re.sub(r"(?<!^)(수원\s*\d{1,2}월)", r"\n\1", value)
    value = re.sub(
        r"(?<!^)(?<!\n)\s+(?=(?:\d{4}\s*타\s*경\s*\d{1,7}|\d{2}\s*[ㅡ\-–—－]\s*\d{1,7})(?:\s*번)?(?:\s|$))",
        "\n",
        value,
    )
    return value


def _empty_row() -> dict:
    return {column: "" for column in FINAL_COLUMNS}


def _format_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _normalize_court(value: str) -> str:
    return "수원" if "수원" in (value or "") else "수원"


def _normalize_case_match(match: re.Match) -> str:
    if match.group("year4"):
        return f"{int(match.group('year4'))}타경{match.group('num4')}"
    return f"{2000 + int(match.group('year2'))}타경{match.group('num2')}"


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _extract_property(line: str) -> str:
    for keyword in PROPERTY_KEYWORDS:
        if keyword == "주택" and not _has_standalone_house_keyword(line):
            continue
        if keyword in line:
            return "오피" if keyword == "오피스텔" else keyword
    return ""


def _has_standalone_house_keyword(line: str) -> bool:
    for match in re.finditer("주택", line):
        previous = line[match.start() - 1] if match.start() > 0 else ""
        if previous not in {"무", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}:
            return True
    return False


def _extract_phones(line: str) -> list[tuple[str, str]]:
    phones: list[tuple[str, str]] = []
    spans: list[tuple[int, int]] = []
    for match in PHONE_010_RE.finditer(line):
        phones.append((f"{match.group(1)}-{match.group(2)}-{match.group(3)}", ""))
        spans.append(match.span())

    for match in PHONE_LOCAL_RE.finditer(line):
        if any(_overlaps(match.span(), span) for span in spans):
            continue
        phones.append((f"{match.group(1)}-{match.group(2)}", "전화번호 앞자리 누락 가능성"))
    return phones


def _extract_item_numbers(line: str) -> list[str]:
    work = _strip_case_date_phone(line)
    work = re.sub(r"(?<=\d)[,./·]+(?=\s*\d)", " ", work)
    items: list[str] = []

    def add_item(value: str) -> None:
        normalized = str(int(value))
        if normalized not in items:
            items.append(normalized)

    for match in ITEM_LIST_RE.finditer(work):
        for number in re.findall(r"\d{1,3}", match.group(1)):
            add_item(number)
    work = ITEM_LIST_RE.sub(" ", work)

    for match in ITEM_EXPLICIT_RE.finditer(work):
        add_item(match.group(1))
    return items


def _extract_remark(line: str) -> str:
    work = _strip_case_date_phone(line)
    work = ITEM_LIST_RE.sub(" ", work)
    work = ITEM_EXPLICIT_RE.sub(" ", work)
    work = re.sub(r"[,:;()\[\]{}]", " ", work)
    work = work.replace(".", " ")
    work = re.sub(r"\b까지는\b|\b까지\b", " ", work)
    remark = _normalize_space(work)
    return "" if remark in PROPERTY_KEYWORDS else remark


def _strip_case_date_phone(line: str) -> str:
    work = CASE_RE.sub(" ", line)
    work = DATE_RE.sub(" ", work)
    work = PHONE_010_RE.sub(" ", work)
    work = PHONE_LOCAL_RE.sub(" ", work)
    return work


def _merge_texts(values: list[str]) -> str:
    merged: list[str] = []
    for value in values:
        value = _normalize_space(value)
        if value and value not in merged:
            merged.append(value)
    return " ".join(merged)


def _append_text(existing: str, addition: str) -> str:
    return _merge_texts([existing, addition])


def _add_rows(
    rows: list[dict],
    row_date: str,
    court: str,
    case_no: str,
    items: list[str],
    phones: list[str],
    property_info: str,
    remark: str,
    reasons: list[str] | None = None,
) -> list[int]:
    indexes: list[int] = []
    reasons = reasons or []
    for index, item in enumerate(items):
        if len(phones) == len(items):
            phone = phones[index]
        elif len(phones) == 1:
            phone = phones[0]
        else:
            phone = phones[0] if phones else ""
            reasons = reasons + ["물건번호와 전화번호 매칭 확인 필요"]

        row = _empty_row()
        row.update(
            {
                "날짜": row_date,
                "법원": _normalize_court(court),
                "사건번호": case_no,
                "물건번호": item,
                "물건정보": property_info,
                "전화번호": phone,
                "비고": remark,
                "확인필요사유": _merge_texts(reasons),
            }
        )
        rows.append(row)
        indexes.append(len(rows) - 1)
    return indexes


def _find_row_indexes(rows: list[dict], case_no: str, items: list[str]) -> list[int]:
    item_set = set(items)
    return [
        index
        for index, row in enumerate(rows)
        if row.get("사건번호") == case_no and str(row.get("물건번호", "")) in item_set
    ]


def _case_has_rows(rows: list[dict], case_no: str) -> bool:
    return any(row.get("사건번호") == case_no for row in rows)


def _append_to_rows(rows: list[dict], indexes: list[int], column: str, text: str) -> None:
    for index in indexes:
        rows[index][column] = _append_text(str(rows[index].get(column, "")), text)


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str, str, str, str], dict] = {}
    for row in rows:
        key = (
            str(row.get("날짜", "")),
            str(row.get("법원", "")),
            str(row.get("사건번호", "")),
            str(row.get("물건번호", "")),
            str(row.get("전화번호", "")),
        )
        if key in deduped:
            deduped[key]["비고"] = _append_text(deduped[key].get("비고", ""), row.get("비고", ""))
            deduped[key]["확인필요사유"] = _append_text(
                deduped[key].get("확인필요사유", ""),
                row.get("확인필요사유", ""),
            )
        else:
            deduped[key] = {column: row.get(column, "") for column in FINAL_COLUMNS}
    return list(deduped.values())


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
