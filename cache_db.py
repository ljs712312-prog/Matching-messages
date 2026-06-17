from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DATA_DIR


DB_PATH = DATA_DIR / "cache.sqlite"

SCHEMA_COLUMNS = {
    "court": "TEXT NOT NULL DEFAULT ''",
    "case_no": "TEXT NOT NULL DEFAULT ''",
    "item_no": "TEXT NOT NULL DEFAULT ''",
    "jibun_address": "TEXT",
    "road_address": "TEXT",
    "full_address": "TEXT",
    "building_name": "TEXT",
    "building_dong": "TEXT",
    "floor": "TEXT",
    "ho": "TEXT",
    "raw_data": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auction_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                court TEXT NOT NULL,
                case_no TEXT NOT NULL,
                item_no TEXT NOT NULL,
                jibun_address TEXT,
                road_address TEXT,
                full_address TEXT,
                building_name TEXT,
                building_dong TEXT,
                floor TEXT,
                ho TEXT,
                raw_data TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(court, case_no, item_no)
            )
            """
        )
        _migrate_columns(conn)
        conn.commit()


def get_cached_item(court: str, case_no: str, item_no: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT jibun_address, road_address, full_address, building_name,
                   building_dong, floor, ho, raw_data
            FROM auction_cache
            WHERE court = ? AND case_no = ? AND item_no = ?
            """,
            (court, case_no, str(item_no)),
        ).fetchone()

    if row is None:
        return None

    raw = {}
    if row["raw_data"]:
        try:
            raw = json.loads(row["raw_data"])
        except json.JSONDecodeError:
            raw = {}

    data = {
        "지번주소": row["jibun_address"] or "",
        "도로명주소": row["road_address"] or "",
        "전체주소": row["full_address"] or row["road_address"] or row["jibun_address"] or "",
        "건물명": row["building_name"] or "",
        "건물동": row["building_dong"] or "",
        "층": row["floor"] or "",
        "호수": row["ho"] or "",
    }
    for key, value in raw.items():
        if value not in (None, ""):
            data[key] = value
    data["전체주소"] = data.get("전체주소") or data.get("도로명주소") or data.get("지번주소") or ""
    return data


def save_cached_item(court: str, case_no: str, item_no: str, data: dict) -> None:
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        "jibun_address": data.get("지번주소") or data.get("jibun_address") or "",
        "road_address": data.get("도로명주소") or data.get("road_address") or "",
        "full_address": (
            data.get("전체주소")
            or data.get("full_address")
            or data.get("도로명주소")
            or data.get("road_address")
            or data.get("지번주소")
            or data.get("jibun_address")
            or ""
        ),
        "building_name": data.get("건물명") or data.get("building_name") or "",
        "building_dong": data.get("건물동") or data.get("building_dong") or "",
        "floor": data.get("층") or data.get("floor") or "",
        "ho": data.get("호수") or data.get("ho") or "",
        "raw_data": json.dumps(data, ensure_ascii=False),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO auction_cache (
                court, case_no, item_no, jibun_address, road_address, full_address,
                building_name, building_dong, floor, ho, raw_data, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(court, case_no, item_no) DO UPDATE SET
                jibun_address = excluded.jibun_address,
                road_address = excluded.road_address,
                full_address = excluded.full_address,
                building_name = excluded.building_name,
                building_dong = excluded.building_dong,
                floor = excluded.floor,
                ho = excluded.ho,
                raw_data = excluded.raw_data,
                updated_at = excluded.updated_at
            """,
            (
                court,
                case_no,
                str(item_no),
                payload["jibun_address"],
                payload["road_address"],
                payload["full_address"],
                payload["building_name"],
                payload["building_dong"],
                payload["floor"],
                payload["ho"],
                payload["raw_data"],
                now,
                now,
            ),
        )
        conn.commit()


def _migrate_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(auction_cache)").fetchall()}
    for name, definition in SCHEMA_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE auction_cache ADD COLUMN {name} {definition}")
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(auction_cache)").fetchall()}
    if "raw_json" in existing:
        conn.execute("UPDATE auction_cache SET raw_data = COALESCE(raw_data, raw_json)")
    if "dong_address" in existing:
        conn.execute("UPDATE auction_cache SET jibun_address = COALESCE(jibun_address, dong_address)")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(Path(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn
