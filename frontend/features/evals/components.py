"""개선 전후 비교 화면의 부품. pages.py가 부른다."""

from __future__ import annotations

import streamlit as st

from core.api import ApiError, api_get, api_post
from core.ui import show_api_error
from features.evals import view

NOTICE_KEY = "_evals_notice"
RESULTS_CACHE_KEY = "_evals_results_cache"   # 끝난 실행의 결과는 바뀌지 않으므로 짝마다 저장
POLL_SEC = 5

# core.ui에 없는 P7 오류 코드: (문구, 다음에 할 일)
LOCAL_ERRORS = {
    "EVAL_CASES_EMPTY": ("기준 세트가 비어 있습니다.",
                         "backend 폴더에서 python scripts/load_eval_cases.py ../eval/eval_cases.json 을 먼저 실행하세요."),
    "EVAL_RUN_IN_PROGRESS": ("이미 진행 중인 평가 실행이 있습니다.", "진행이 끝난 뒤 다시 실행하세요."),
    "EVAL_RUN_NOT_FOUND": ("평가 실행을 찾을 수 없습니다.", "실행 목록을 새로 고친 뒤 다시 고르세요."),
}


def show_error(e: ApiError) -> None:
    if e.code in LOCAL_ERRORS:
        message, next_step = LOCAL_ERRORS[e.code]
        st.error(f"{message} {next_step}")
        rid = (e.detail or {}).get("request_id")
        if rid:
            st.caption(f"문의 시 요청 번호: {rid}")
    else:
        show_api_error(e)


def load_runs() -> list[dict] | None:
    try:
        with st.spinner("실행 목록을 불러오는 중…"):
            return api_get("/admin/eval-runs") or []
    except ApiError as e:
        show_error(e)
        if st.button("다시 시도", key="evals_retry_runs"):
            st.rerun()
        return None


# ------------------------------------------------------------------ 실행
def run_section(runs: list[dict]) -> None:
    st.subheader("실행")
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.success(notice)

    running = view.active_running(runs)
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    version = c1.selectbox("프롬프트 버전", view.PROMPT_VERSIONS, key="evals_prompt_version",
                           help="같은 기준 세트·모델·설정으로 돌립니다. 버전만 바꿔 비교하세요.")
    clicked = c2.button("평가 실행", type="primary", key="evals_start", width="stretch", disabled=bool(running))
    st.caption("사례마다 AI를 한 번 부르고, 무료 등급 한도 때문에 사례 사이에 몇 초씩 쉽니다(20건이면 1~3분).")

    if clicked:
        try:
            with st.spinner("실행을 시작하는 중…"):
                api_post("/admin/eval-runs", json={"prompt_version": version})
        except ApiError as e:
            show_error(e)
        else:
            st.session_state[NOTICE_KEY] = f"{version} 평가를 시작했습니다. 진행 상태를 아래에서 확인하세요."
            st.rerun()

    if running:
        _watch_running()


def _watch_running() -> None:
    """진행 중인 실행이 있을 때만 몇 초마다 다시 읽는다. 끝나면 화면 전체를 새로 그린다."""

    @st.fragment(run_every=POLL_SEC)
    def _watch() -> None:
        try:
            runs = api_get("/admin/eval-runs") or []
        except ApiError as e:
            show_error(e)
            st.caption("연결이 돌아오면 자동으로 다시 확인합니다.")
            return
        running = view.active_running(runs)
        if not running:
            st.session_state[NOTICE_KEY] = "평가 실행이 끝났습니다. 아래에서 결과를 비교하세요."
            st.rerun()   # 프래그먼트 안에서 부르면 화면 전체를 다시 그린다
            return
        for r in running:
            done, total = int(r.get("result_count") or 0), int(r.get("case_count") or 0)
            ratio = min(done / total, 1.0) if total else 0.0
            st.progress(ratio, text=f"{r.get('prompt_version')} 실행 중 — {done}/{total}건 끝남")
        st.caption(f"{POLL_SEC}초마다 자동으로 확인합니다. "
                   f"{view.STALE_MINUTES}분이 지나도 끝나지 않으면 멈춘 것으로 보고 새 실행을 허용합니다.")

    _watch()


# ------------------------------------------------------------------ 실행 목록
def runs_table(runs: list[dict]) -> None:
    st.subheader("실행 목록")
    if not runs:
        st.info("아직 실행한 평가가 없습니다. 위에서 v1을 먼저 실행하세요.")
        return
    st.dataframe(view.run_list_rows(runs), hide_index=True, width="stretch")
    failed = [r for r in runs if r.get("status") == "failed"]
    if failed:
        with st.expander(f"실패한 실행 {len(failed)}건"):
            for r in failed:
                st.markdown(f"- {view.run_label(r)} — {r.get('error_message') or '이유 미기록'}")
            st.caption("원인을 고친 뒤 같은 버전으로 다시 실행하세요.")


# ------------------------------------------------------------------ 비교
def _fetch_compare(after_id: str, before_id: str) -> dict | None:
    cache = st.session_state.setdefault(RESULTS_CACHE_KEY, {})
    key = f"{after_id}:{before_id}"
    if key in cache:
        return cache[key]
    try:
        with st.spinner("사례별 결과를 불러오는 중…"):
            data = api_get(f"/admin/eval-runs/{after_id}/results", params={"compare_to": before_id})
    except ApiError as e:
        show_error(e)
        if st.button("다시 시도", key="evals_retry_compare"):
            st.rerun()
        return None
    cache[key] = data
    return data


def compare_section(runs: list[dict]) -> None:
    st.subheader("개선 전후 비교")
    done = [r for r in runs if r.get("status") == "done"]
    if len(done) < 2:
        st.info("완료된 실행이 2개 이상 있어야 비교할 수 있습니다. v1과 v2를 각각 실행하세요.")
        return

    i_before, i_after = view.default_pair(done)
    by_id = {r["id"]: r for r in done}
    ids = list(by_id)
    c1, c2 = st.columns(2)
    before_id = c1.selectbox("개선 전", ids, index=i_before, format_func=lambda i: view.run_label(by_id[i]),
                             key="evals_before")
    after_id = c2.selectbox("개선 후", ids, index=i_after, format_func=lambda i: view.run_label(by_id[i]),
                            key="evals_after")
    before, after = by_id[before_id], by_id[after_id]
    if before["id"] == after["id"]:
        st.warning("서로 다른 실행 두 개를 고르세요.")
        return

    data = _fetch_compare(after["id"], before["id"])
    if data is None:
        return
    run_b, run_a = data.get("compare_run") or before, data.get("run") or after

    mismatches = data.get("condition_mismatches") or []
    if mismatches:
        names = ", ".join(view.CONDITION_LABELS.get(m, m) for m in mismatches)
        st.warning(f"비교 조건이 다릅니다: {names}. 같은 기준 세트·모델·설정으로 다시 실행해야 공정한 비교입니다.",
                   icon="⚠️")
    else:
        st.caption(f"같은 조건: 모델 {run_a.get('model')} · thinking_level {run_a.get('thinking_level') or '-'} · "
                   f"스키마 {run_a.get('schema_version')} · 사례 {run_a.get('case_count')}건")
    ai_errors = int(run_b.get("error_case_count") or 0) + int(run_a.get("error_case_count") or 0)
    if ai_errors:
        st.warning(f"AI 오류(시간 초과·한도 초과)로 끝난 사례가 {ai_errors}건 있습니다. "
                   "이 사례는 모든 필드가 불일치로 계산됐습니다. 정확한 비교가 필요하면 다시 실행하세요.")

    st.markdown("**지표**")
    st.dataframe(view.metric_rows(run_b, run_a), hide_index=True, width="stretch")
    with st.expander("지표 계산 방법"):
        st.markdown(
            "- 필드 정확도: 일치한 평가 필드 ÷ 전체 평가 필드(사례 × 8필드, 출력이 없으면 불일치)\n"
            "- 환각률: 정답이 null인데 값이 있는 필드 ÷ 정답이 null인 필드(금액 3·층수·방향, 출력 있는 사례만)\n"
            "- 빠진 항목 정확도: missing_checks 집합이 정확히 맞은 사례 ÷ 전체 사례\n"
            "- 형식 실패율: 재시도 후에도 형식이 실패한 사례 ÷ 전체 사례\n"
            "- 사용자가 고친 빈도(운영 대시보드의 필드 수정 비율)와는 다른 지표입니다."
        )

    st.markdown("**실패 유형별 사례 수**")
    st.dataframe(view.failure_rows(run_b, run_a), hide_index=True, width="stretch")

    _case_list(data.get("results") or [])


def _case_list(results: list[dict]) -> None:
    st.markdown("**사례별 결과**")
    if not results:
        st.info("저장된 사례 결과가 없습니다. 실행 목록에서 진행 상태를 확인하세요.")
        return
    c1, c2 = st.columns([1, 2])
    only_changed = c1.toggle("달라진 사례만", key="evals_only_changed")
    all_tags = sorted({t for r in results for t in (r.get("tags") or [])})
    tags = c2.multiselect("유형(tags)", all_tags, key="evals_tags", placeholder="전체")

    shown = [r for r in results
             if (not only_changed or view.case_changed(r))
             and (not tags or set(tags) & set(r.get("tags") or []))]
    st.caption(f"{len(shown)} / {len(results)}건 · CLS(장단점 오분류)는 아래 '사람이 판단할 항목'을 보고 정합니다.")
    if not shown:
        st.info("조건에 맞는 사례가 없습니다. 필터를 바꿔 보세요.")
        return
    for item in shown:
        with st.expander(view.case_title(item)):
            if item.get("criteria"):
                st.info(f"볼 점: {item['criteria']}")
            st.text_area("메모", item.get("memo_text") or "", disabled=True, height=80,
                         key=f"evals_memo_{item.get('case_id')}")
            st.dataframe(view.case_field_rows(item), hide_index=True, width="stretch")
            st.markdown("사람이 판단할 항목")
            st.dataframe(view.case_human_rows(item), hide_index=True, width="stretch")
