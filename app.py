from __future__ import annotations

import importlib
from datetime import datetime

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
    st.caption(
        "문자 원본을 붙여 넣으면 사건번호, 물건번호, 전화번호, 물건정보, 비고를 정리하고 "
        "법원경매정보에서 주소, 동, 층, 호수를 조회해 엑셀로 내려받습니다."
    )

    if not _is_logged_in():
        _render_login()
        st.stop()

    original_text = st.text_area(
        "문자 원본",
        height=260,
        placeholder="문자 내용을 그대로 붙여 넣으세요.",
    )

    left, right = st.columns([1, 4])
    with left:
        parse_clicked = st.button("문자 해석", type="primary", use_container_width=True)
    with right:
        actual_lookup = st.checkbox(
            "실제 법원경매정보 조회",
            value=st.session_state.get("actual_lookup", True),
            help="체크하면 주소, 동, 층, 호수 조회 실행 때 법원경매정보 사이트를 실제 조회합니다.",
        )
        st.session_state["actual_lookup"] = actual_lookup
        st.write(f"지번 변환: {address_conversion_status()}")

    if parse_clicked:
        rows = parse_sms(original_text, default_court=DEFAULT_COURT, default_year=DEFAULT_YEAR)
        st.session_state["original_text"] = original_text
        st.session_state["rows"] = rows
        st.session_state["looked_up"] = False
        st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
        st.session_state["lookup_message"] = ""

    rows = st.session_state.get("rows", [])
    if not rows:
        st.info("문자를 붙여 넣고 `문자 해석`을 누르면 결과 표가 표시됩니다.")
        return

    st.subheader("해석 결과")
    editor_key = f"result_editor_{st.session_state.get('editor_version', 0)}"
    edited_df = st.data_editor(
        pd.DataFrame(rows, columns=FINAL_COLUMNS),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=editor_key,
    )
    edited_rows = _df_to_rows(edited_df)
    st.session_state["rows"] = edited_rows

    lookup_clicked = st.button("주소/호수 조회 실행", type="primary", use_container_width=True)
    progress_area = st.container()

    if lookup_clicked:
        with progress_area:
            progress_bar = st.progress(0, text="주소/호수 조회 준비 중")
            progress_text = st.empty()

            def update_progress(done: int, total: int, message: str) -> None:
                ratio = 0 if total <= 0 else min(1.0, done / total)
                progress_bar.progress(ratio, text=message)
                progress_text.write(f"{done}/{total}건 완료")

            lookup_module = importlib.reload(court_playwright)
            looked_up_rows = lookup_module.lookup_auction_items(
                edited_rows,
                progress_callback=update_progress,
                lookup_enabled=actual_lookup,
            )
            st.session_state["rows"] = looked_up_rows
            st.session_state["looked_up"] = True
            st.session_state["lookup_message"] = f"주소/호수 조회 완료: {len(looked_up_rows)}건 처리"
            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
            st.success(st.session_state["lookup_message"])
            st.dataframe(pd.DataFrame(looked_up_rows, columns=FINAL_COLUMNS), use_container_width=True, hide_index=True)
    elif st.session_state.get("lookup_message"):
        progress_area.success(st.session_state["lookup_message"])

    download_rows = st.session_state.get("rows", edited_rows)
    excel_bytes = build_excel(download_rows, st.session_state.get("original_text", original_text))
    st.download_button(
        "엑셀 다운로드",
        data=excel_bytes,
        file_name=f"경매_주소조회_결과_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
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


if __name__ == "__main__":
    main()
