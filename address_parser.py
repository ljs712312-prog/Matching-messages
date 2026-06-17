from __future__ import annotations

import re


JIBUN_RE = re.compile(r"([가-힣]+동|[가-힣]+리|[가-힣]+읍|[가-힣]+면)\s*\d+(?:-\d+)?")
ROAD_RE = re.compile(
    r"((?:[가-힣]+(?:시|도|군|구)\s+){1,5}[가-힣0-9]+(?:로|길)\s*\d+(?:-\d+)?)"
)
PAREN_RE = re.compile(r"\(([^)]*)\)")
BUILDING_DONG_RE = re.compile(
    r"(?:제\s*)?(\d{1,4}|[A-Za-z]|에이|비|씨|디|이|에프|가|나|다|라|마|바|사|아)\s*동"
)
FLOOR_RE = re.compile(r"(?:제\s*)?(\d{1,3})\s*층")
HO_RE = re.compile(r"(?:제\s*)?(\d{1,4})\s*호")


def parse_address(full_address: str, road_address: str = "") -> dict:
    text = _normalize(full_address)
    road = _normalize(road_address)
    result = {
        "지번주소": "",
        "도로명주소": road,
        "전체주소": text,
        "건물명": "",
        "건물동": "",
        "층": "",
        "호수": "",
        "확인필요사유": "",
    }
    if not text and not road:
        result["확인필요사유"] = "지번주소 미확인 도로명주소 미확인"
        return result

    jibun_match = JIBUN_RE.search(text)
    if jibun_match:
        result["지번주소"] = _normalize(jibun_match.group(0))

    if not result["도로명주소"]:
        road_match = ROAD_RE.search(text)
        if road_match:
            result["도로명주소"] = _normalize(road_match.group(1))

    work = _remove_location_parts(text, result["지번주소"], result["도로명주소"])
    work = _remove_location_dong_from_parentheses(work)

    dong_match = BUILDING_DONG_RE.search(work)
    if dong_match:
        result["건물동"] = _normalize_building_dong(dong_match.group(1))

    floor_match = FLOOR_RE.search(text)
    if floor_match:
        result["층"] = f"{int(floor_match.group(1))}층"

    ho_match = HO_RE.search(text)
    if ho_match:
        result["호수"] = f"{int(ho_match.group(1))}호"
        if not result["층"] and len(ho_match.group(1)) >= 3:
            result["층"] = f"{int(ho_match.group(1)[:-2])}층"

    result["건물명"] = _extract_building_name(text, result)

    reasons: list[str] = []
    if not result["지번주소"]:
        reasons.append("지번주소 미확인")
    if road_address and not result["도로명주소"]:
        reasons.append("도로명주소 미확인")
    result["확인필요사유"] = " ".join(reasons)
    return result


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_building_dong(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return f"{int(value)}동"
    if re.fullmatch(r"[A-Za-z]", value):
        return f"{value.upper()}동"
    return f"{value}동"


def _remove_location_parts(text: str, jibun_address: str, road_address: str) -> str:
    work = text
    if jibun_address:
        work = work.replace(jibun_address, " ")
    if road_address:
        work = work.replace(road_address, " ")
    return _normalize(work)


def _remove_location_dong_from_parentheses(text: str) -> str:
    def replace(match: re.Match) -> str:
        parts = [part.strip() for part in match.group(1).split(",") if part.strip()]
        parts = [part for part in parts if not re.fullmatch(r"[가-힣]+동|[가-힣]+리", part)]
        return f"({','.join(parts)})" if parts else " "

    return _normalize(PAREN_RE.sub(replace, text))


def _extract_building_name(text: str, parsed: dict) -> str:
    parenthetical = _building_from_parentheses(text)
    if parenthetical:
        return parenthetical

    candidate = text
    for key in ["지번주소", "도로명주소", "건물동", "층", "호수"]:
        value = parsed.get(key, "")
        if value:
            candidate = candidate.replace(value, " ")
    candidate = PAREN_RE.sub(" ", candidate)
    candidate = FLOOR_RE.sub(" ", candidate)
    candidate = HO_RE.sub(" ", candidate)
    candidate = BUILDING_DONG_RE.sub(" ", candidate)
    candidate = re.sub(r"\b\d+(?:-\d+)?\b", " ", candidate)
    candidate = re.sub(r"[,\[\]{}()]", " ", candidate)
    return _normalize(candidate)


def _building_from_parentheses(text: str) -> str:
    for match in PAREN_RE.finditer(text):
        parts = [part.strip() for part in match.group(1).split(",") if part.strip()]
        for part in reversed(parts):
            if re.fullmatch(r"[가-힣]+동|[가-힣]+리", part):
                continue
            return part
    return ""
