import json
from pathlib import Path

import streamlit as st

from ui_service import lookup_histories, run_manual, validate_versions, version_label

RESULT_PATH = Path(__file__).with_name("scan_results.json")


def clear_result():
    st.session_state.pop("manual_result", None)
    st.session_state.pop("changed_search", None)


def clear_lookup():
    clear_result()
    for key in ("histories", "loaded_law", "current_version", "previous_version"):
        st.session_state.pop(key, None)


def manual_controls():
    st.sidebar.text_input(
        "정확한 법령명", value="법인세법 시행규칙", key="law_name",
        placeholder="예: 조세특례제한법 시행규칙", on_change=clear_lookup,
    )
    name = st.session_state.law_name.strip()
    st.sidebar.caption("다른 법령도 정확한 이름을 직접 입력할 수 있습니다.")
    if st.sidebar.button("현행·연혁 조회", key="lookup", disabled=not name):
        clear_lookup()
        try:
            with st.spinner("현행·연혁 목록을 조회하고 있습니다."):
                histories = lookup_histories(name)
            st.session_state.histories = histories
            st.session_state.loaded_law = name
        except Exception:
            # HTTP exception messages may contain OC in their request URL.
            st.sidebar.error("연혁 조회에 실패했습니다. 정확한 법령명, LAW_OC 환경 설정 및 API 연결을 확인하세요.")

    histories = st.session_state.get("histories", [])
    if st.session_state.get("loaded_law") != name:
        return None
    st.sidebar.caption(f"현행·연혁 {len(histories)}개 · 시행일 내림차순")
    if len(histories) < 2:
        st.sidebar.warning("비교하려면 서로 다른 버전이 2개 이상 필요합니다.")
        return None
    ci = st.sidebar.selectbox(
        "현재 버전 (비교 대상)", range(len(histories)),
        format_func=lambda i: version_label(histories[i]), key="current_version",
        on_change=clear_result,
    )
    pi = st.sidebar.selectbox(
        "기준 버전 (이전)", range(len(histories)), index=1,
        format_func=lambda i: version_label(histories[i]), key="previous_version",
        on_change=clear_result,
    )
    current, previous = histories[ci], histories[pi]
    valid = True
    try:
        validate_versions(current, previous)
    except ValueError:
        valid = False
        st.sidebar.warning("서로 다른 버전을 선택하고, 현재 시행일이 기준 시행일보다 같거나 늦도록 설정하세요.")
    st.sidebar.caption("첫 항목은 최신 시행일의 버전입니다. 비교할 시행일과 MST를 확인하세요.")
    if st.sidebar.button("MANUAL Scanner 실행", key="run_scan", disabled=not valid):
        clear_result()
        status = st.empty()
        try:
            with st.spinner("전체 서식을 비교하고 있습니다. 서식 수에 따라 시간이 걸릴 수 있습니다."):
                st.session_state.manual_result = run_manual(name, current, previous, progress=status.info)
        except Exception:
            st.error("Scanner 실행에 실패했습니다. LAW_OC 환경 설정 및 API 연결을 확인한 뒤 다시 실행하세요.")
        finally:
            status.empty()
    st.sidebar.caption("실행 결과는 현재 세션 메모리에만 보관됩니다. 새로고침하면 사라질 수 있습니다.")
    return st.session_state.get("manual_result")


def render_result(data):
    if data.get("status") == "partial":
        st.warning("일부 서식 비교가 완료되지 않았습니다. 확인 필요 탭을 확인하세요.")
    st.subheader(data.get("law_name", "법령명 없음"))

    current = data.get("current", {})
    previous = data.get("previous", {})

    st.write(
        f"**기준 연혁:** {previous.get('effective_date', '-')} "
        f"→ **현재 연혁:** {current.get('effective_date', '-')}"
    )

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("전체", data.get("current_count", 0))
    col2.metric("신규", len(data.get("new_forms", [])))
    col3.metric("삭제", len(data.get("deleted_forms", [])))
    col4.metric("변경", len(data.get("changed_forms", [])))
    col5.metric(
        "확인 필요",
        len(data.get("review_required_forms", [])),
    )

    st.divider()


    # --------------------------------------------------
    # 결과 데이터
    # --------------------------------------------------

    changed_forms = data.get("changed_forms", [])
    new_forms = data.get("new_forms", [])
    deleted_forms = data.get("deleted_forms", [])
    review_forms = data.get("review_required_forms", [])


    # --------------------------------------------------
    # 탭
    # --------------------------------------------------

    tab_changed, tab_new, tab_deleted, tab_review = st.tabs(
        [
            f"변경 {len(changed_forms)}",
            f"신규 {len(new_forms)}",
            f"삭제 {len(deleted_forms)}",
            f"확인 필요 {len(review_forms)}",
        ]
    )


    # --------------------------------------------------
    # 변경 탭
    # --------------------------------------------------

    with tab_changed:

        search_text = st.text_input(
            "서식번호 또는 서식명 검색",
            placeholder="예: 0003 또는 세액조정계산서",
            key="changed_search",
        )

        filtered_forms = changed_forms

        if search_text:
            keyword = search_text.replace(" ", "").lower()

            filtered_forms = [
                form
                for form in changed_forms
                if keyword
                in (
                    str(form.get("number", ""))
                    + str(form.get("branch_number", ""))
                    + str(form.get("title", ""))
                )
                .replace(" ", "")
                .lower()
            ]

        st.write(f"검색 결과: **{len(filtered_forms)}개 서식**")

        if not filtered_forms:
            st.info("검색 조건에 해당하는 변경 서식이 없습니다.")

        for form in filtered_forms:

            number = form.get("number", "")
            branch = form.get("branch_number", "")
            title = form.get("title", "")

            comparison = form.get("comparison", {})
            changes = comparison.get("changes", [])

            with st.expander(
                f"{number}-{branch}  {title} ({len(changes)}건)"
            ):

                if not changes:
                    st.info("상세 변경 내용이 없습니다.")
                    continue

                rows = []

                for index, change in enumerate(changes, start=1):

                    type_label = {
                        "replace": "🟡 변경",
                        "insert": "🟢 추가",
                        "delete": "🔴 삭제",
                    }.get(
                        change.get("type", ""),
                        change.get("type", ""),
                    )

                    rows.append(
                        {
                            "순번": index,
                            "유형": type_label,
                            "이전 내용": change.get("old", ""),
                            "현재 내용": change.get("new", ""),
                        }
                    )

                st.dataframe(
                    rows,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "순번": st.column_config.NumberColumn(
                            "순번",
                            width="small",
                        ),
                        "유형": st.column_config.TextColumn(
                            "유형",
                            width="small",
                        ),
                        "이전 내용": st.column_config.TextColumn(
                            "이전 내용",
                            width="large",
                        ),
                        "현재 내용": st.column_config.TextColumn(
                            "현재 내용",
                            width="large",
                        ),
                    },
                )


    # --------------------------------------------------
    # 신규 탭
    # --------------------------------------------------

    with tab_new:

        if not new_forms:
            st.info("신규 서식이 없습니다.")

        else:
            for form in new_forms:
                st.write(
                    f"**{form.get('number', '')}-"
                    f"{form.get('branch_number', '')}** "
                    f"{form.get('title', '')}"
                )


    # --------------------------------------------------
    # 삭제 탭
    # --------------------------------------------------

    with tab_deleted:

        if not deleted_forms:
            st.info("삭제 서식이 없습니다.")

        else:
            for form in deleted_forms:
                st.write(
                    f"**{form.get('number', '')}-"
                    f"{form.get('branch_number', '')}** "
                    f"{form.get('title', '')}"
                )


    # --------------------------------------------------
    # 확인 필요 탭
    # --------------------------------------------------

    with tab_review:

        if not review_forms:
            st.success("확인 필요한 서식이 없습니다.")

        else:
            for form in review_forms:
                st.warning(
                    f"{form.get('number', '')}-"
                    f"{form.get('branch_number', '')} "
                    f"{form.get('title', '')} / "
                    f"{form.get('failed_stage', '')}"
                )

def main():
    st.set_page_config(page_title="법령서식 변경감지", layout="wide")
    st.title("법령서식 Scanner / Comparator")
    source = st.sidebar.radio("결과 선택", ["저장된 결과 (읽기 전용)", "법령·버전 선택 후 실행"], key="result_source", on_change=clear_result)
    if source == "저장된 결과 (읽기 전용)":
        try:
            data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("invalid result")
        except FileNotFoundError:
            st.warning("scan_results.json 파일이 없습니다. 사이드바에서 법령·버전 선택 후 실행을 선택하세요.")
            return
        except (OSError, ValueError):
            st.error("scan_results.json 파일을 읽을 수 없습니다. 파일 형식을 확인하세요.")
            return
        st.caption("저장된 scan_results.json · 읽기 전용")
    else:
        data = manual_controls()
        if data is None:
            st.info("사이드바에서 법령명을 조회하고 현재·기준 버전을 선택한 뒤 MANUAL Scanner를 실행하세요.")
            return
        st.caption("MANUAL 실행 결과 · 현재 세션")
    render_result(data)


if __name__ == "__main__":
    main()
