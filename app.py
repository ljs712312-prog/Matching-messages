from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import court_playwright
from address_converter import address_conversion_status
from config import DEFAULT_COURT, DEFAULT_YEAR, OFFICE_PASSWORD, load_env_files
from excel_exporter import build_excel
from sms_parser import FINAL_COLUMNS, parse_sms


st.set_page_config(page_title="법원 경매 문자 주소조회", layout="wide")


def main() -> None:
    load_env_files()

    st.title("법원 경매 문자 주소조회")
    st.caption("문자 정리와 사건번호 빠른 조회를 한 곳에서 처리하고 결과를 엑셀로 내려받습니다.")

    if not _is_logged_in():
        _render_login()
        st.stop()

    option_col, status_col = st.columns([1, 3])
    with option_col:
        actual_lookup = st.checkbox(
            "실제 법원경매정보 조회",
            value=st.session_state.get("actual_lookup", True),
            help="체크하면 법원경매정보 사이트에서 주소, 동, 층, 호수를 조회합니다.",
        )
        st.session_state["actual_lookup"] = actual_lookup
    with status_col:
        st.write(f"지번 변환: {address_conversion_status()}")

    sms_tab, quick_tab = st.tabs(["문자 전체 정리", "사건번호 빠른 조회"])
    with sms_tab:
        _render_sms_tab(actual_lookup)
    with quick_tab:
        _render_quick_tab(actual_lookup)


def _render_sms_tab(actual_lookup: bool) -> None:
    original_text = st.text_area(
        "문자 원본",
        height=260,
        placeholder="수원 6월 17일\n24-14090 2번 상가\n대출많이 요구\n010 6667 1625번",
        key="sms_input",
    )
    if st.button("문자 해석", type="primary", use_container_width=True, key="sms_parse"):
        rows = parse_sms(original_text, default_court=DEFAULT_COURT, default_year=DEFAULT_YEAR)
        _set_new_rows("sms", rows, original_text)

    _render_workspace("sms", actual_lookup, empty_message="문자를 붙여 넣고 `문자 해석`을 누르세요.")


def _render_quick_tab(actual_lookup: bool) -> None:
    st.caption("사건번호만 한 줄씩 넣어도 물건번호 1번으로 조회합니다. 물건번호가 다르면 `2번`처럼 함께 적으세요.")
    court_col, date_col = st.columns(2)
    with court_col:
        court = st.text_input("법원", value=DEFAULT_COURT, key="quick_court")
    with date_col:
        lookup_date = st.date_input("정리 날짜", value=date.today(), key="quick_date")

    query_text = st.text_area(
        "사건번호 목록",
        height=220,
        placeholder=(
            "24-14090 2번 상가\n"
            "24-69267 아파트\n"
            "2025타경886 빌라\n"
            "25-55383 빌라"
        ),
        key="quick_input",
    )
    if st.button("조회 목록 만들기", type="primary", use_container_width=True, key="quick_parse"):
        header = f"{court.strip() or DEFAULT_COURT} {lookup_date.month}월 {lookup_date.day}일"
        source_text = f"{header}\n{query_text.strip()}"
        rows = parse_sms(source_text, default_court=court or DEFAULT_COURT, default_year=lookup_date.year)
        for row in rows:
            row["날짜"] = lookup_date.isoformat()
            row["법원"] = court.strip() or DEFAULT_COURT
        _set_new_rows("quick", rows, query_text)

    _render_workspace("quick", actual_lookup, empty_message="사건번호를 입력하고 `조회 목록 만들기`를 누르세요.")


def _set_new_rows(prefix: str, rows: list[dict], original_text: str) -> None:
    st.session_state[f"{prefix}_original_text"] = original_text
    st.session_state[f"{prefix}_rows"] = rows
    st.session_state[f"{prefix}_lookup_identities"] = []
    st.session_state[f"{prefix}_editor_version"] = st.session_state.get(f"{prefix}_editor_version", 0) + 1
    st.session_state[f"{prefix}_lookup_message"] = ""


def _render_workspace(prefix: str, actual_lookup: bool, empty_message: str) -> None:
    rows = st.session_state.get(f"{prefix}_rows", [])
    if not rows:
        st.info(empty_message)
        return

    st.subheader("해석 결과")
    st.caption("사건번호, 물건번호, 법원, 물건정보를 바로 수정할 수 있습니다.")
    editor_key = f"{prefix}_editor_{st.session_state.get(f'{prefix}_editor_version', 0)}"
    edited_df = st.data_editor(
        pd.DataFrame(rows, columns=FINAL_COLUMNS),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=_editor_column_config(),
        key=editor_key,
    )
    edited_rows = _df_to_rows(edited_df)

    apply_col, lookup_col = st.columns([1, 3])
    with apply_col:
        apply_clicked = st.button("수정사항 적용", use_container_width=True, key=f"{prefix}_apply")
    with lookup_col:
        lookup_clicked = st.button(
            "주소/호수 조회 실행",
            type="primary",
            use_container_width=True,
            key=f"{prefix}_lookup",
        )
    progress_area = st.container()

    if apply_clicked:
        applied_rows = _prepare_rows_after_edit(edited_rows, prefix)
        st.session_state[f"{prefix}_rows"] = applied_rows
        st.session_state[f"{prefix}_lookup_identities"] = [_row_identity(row) for row in applied_rows]
        st.session_state[f"{prefix}_lookup_message"] = "수정사항이 적용됐습니다. 이 표를 기준으로 조회합니다."
        st.session_state[f"{prefix}_editor_version"] = st.session_state.get(f"{prefix}_editor_version", 0) + 1
        st.rerun()

    if lookup_clicked:
        edited_rows = _prepare_rows_after_edit(edited_rows, prefix)
        st.session_state[f"{prefix}_rows"] = edited_rows
        with progress_area:
            progress_bar = st.progress(0, text="주소/호수 조회 준비 중")
            progress_text = st.empty()

            def update_progress(done: int, total: int, message: str) -> None:
                ratio = 0 if total <= 0 else min(1.0, done / total)
                progress_bar.progress(ratio, text=message)
                progress_text.write(f"{done}/{total}건 완료")

            looked_up_rows = court_playwright.lookup_auction_items(
                edited_rows,
                progress_callback=update_progress,
                lookup_enabled=actual_lookup,
            )
            st.session_state[f"{prefix}_rows"] = looked_up_rows
            st.session_state[f"{prefix}_lookup_identities"] = [_row_identity(row) for row in looked_up_rows]
            st.session_state[f"{prefix}_lookup_message"] = f"주소/호수 조회 완료: {len(looked_up_rows)}건 처리"
            st.session_state[f"{prefix}_editor_version"] = st.session_state.get(f"{prefix}_editor_version", 0) + 1
            edited_rows = looked_up_rows
            st.success(st.session_state[f"{prefix}_lookup_message"])
            st.dataframe(pd.DataFrame(looked_up_rows, columns=FINAL_COLUMNS), use_container_width=True, hide_index=True)
    elif st.session_state.get(f"{prefix}_lookup_message"):
        progress_area.success(st.session_state[f"{prefix}_lookup_message"])

    download_rows = _prepare_rows_after_edit(edited_rows, prefix)
    original_text = st.session_state.get(f"{prefix}_original_text", "")
    excel_bytes = build_excel(download_rows, original_text)
    st.download_button(
        "엑셀 다운로드",
        data=excel_bytes,
        file_name=f"경매_주소조회_결과_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        key=f"{prefix}_download",
    )


def _is_logged_in() -> bool:
    return bool(st.session_state.get("authenticated"))


def _render_login() -> None:
    with st.form("login_form"):
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", use_container_width=True)
    if submitted:
        if password == OFFICE_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")


def _df_to_rows(dataframe: pd.DataFrame) -> list[dict]:
    cleaned = dataframe.fillna("")
    return [
        {column: str(row.get(column, "")).strip() for column in FINAL_COLUMNS}
        for row in cleaned.to_dict(orient="records")
    ]


def _editor_column_config() -> dict:
    return {
        "날짜": st.column_config.TextColumn("날짜", width="small"),
        "법원": st.column_config.TextColumn("법원", help="예: 수원", width="small"),
        "사건번호": st.column_config.TextColumn("사건번호", help="예: 2024타경3625", width="medium"),
        "물건번호": st.column_config.TextColumn("물건번호", help="예: 1, 4, 11", width="small"),
        "물건정보": st.column_config.TextColumn("물건정보", help="예: 빌라, 아파트, 오피", width="small"),
        "비고": st.column_config.TextColumn("비고", width="large"),
    }


def _prepare_rows_after_edit(rows: list[dict], prefix: str) -> list[dict]:
    previous_identities = st.session_state.get(f"{prefix}_lookup_identities", [])
    prepared_rows: list[dict] = []
    for index, row in enumerate(rows):
        prepared = {column: str(row.get(column, "")).strip() for column in FINAL_COLUMNS}
        if index < len(previous_identities) and _row_identity(prepared) != tuple(previous_identities[index]):
            _clear_lookup_result(prepared)
        prepared_rows.append(prepared)
    return prepared_rows


def _row_identity(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("법원", "")).strip(),
        str(row.get("사건번호", "")).strip(),
        str(row.get("물건번호", "")).strip(),
        str(row.get("물건정보", "")).strip(),
    )


def _clear_lookup_result(row: dict) -> None:
    for column in ["지번주소", "도로명주소", "전체주소", "건물명", "건물동", "층", "호수"]:
        row[column] = ""
    row["조회상태"] = ""
    row["확인필요사유"] = ""


if __name__ == "__main__":
    main()
