"""항목 가중치 화면 부품. st를 쓰지 않는 순수 함수만 둔다(테스트하기 쉽게)."""

from __future__ import annotations

NO_PROFILE_LABEL = "선택 안 함 (모든 항목 같은 가중치)"
UNRATED = "미입력"
RULE_NOTE = ("적합도 = Σ(가중치 × 만족도) ÷ Σ가중치 (0~100점). 만족도를 입력하지 않은 항목은 빼고 계산하고, "
             "가중치가 모두 0이거나 프로필을 고르지 않으면 모든 항목을 같은 비중으로 봅니다.")
SATISFACTION_NOTE = ("직접 보고 느낀 만족도를 0~100으로 적으세요. 높을수록 좋음으로 통일합니다"
                     "(예: 곰팡이 → 곰팡이가 없을수록 높게). 비워 둔 항목은 점수 계산에서 뺍니다.")


def profile_options(profiles: list[dict] | None) -> list[str | None]:
    """선택 상자 값 목록. 맨 앞 None = 프로필 없음(동일 가중치)."""
    return [None] + [p["id"] for p in (profiles or [])]


def profile_label(pid: str | None, profiles: list[dict] | None) -> str:
    if pid is None:
        return NO_PROFILE_LABEL
    for p in profiles or []:
        if p["id"] == pid:
            return p["name"]
    return "(지워진 프로필)"


def weights_summary(profile: dict | None) -> str:
    """'채광 50 · 소음 30 …'. 가중치 0인 항목은 뺀다."""
    if not profile:
        return "모든 항목 같은 가중치"
    parts = [f"{w['item_key']} {w['weight']}" for w in profile.get("weights") or [] if w.get("weight")]
    return " · ".join(parts) if parts else "가중치가 모두 0 → 모든 항목 같은 가중치"


def weights_body(name: str, weights: dict[str, int | float | None]) -> dict:
    """프로필 만들기·고치기 본문. 빈 값은 0."""
    return {"name": (name or "").strip(),
            "weights": [{"item_key": k, "weight": int(v or 0)} for k, v in weights.items()]}


def satisfaction_body(values: dict[str, int | float | None]) -> dict:
    """만족도 저장 본문. 빈 칸(None)은 보내지 않는다 = 미입력."""
    return {"items": [{"item_key": k, "satisfaction": int(v)} for k, v in values.items() if v is not None]}


def fmt_score(score: int | None) -> str:
    return UNRATED if score is None else f"{int(score)}점"


def _md(text: str) -> str:
    return str(text).replace("|", "\\|")


def ranking_markdown(rows: list[dict]) -> str:
    """ScoresOut.rows → 마크다운 표(순위·매물·적합도·입력한 항목)."""
    lines = ["| 순위 | 매물 | 적합도 | 입력한 항목 |", "|---|---|---|---|"]
    for r in rows:
        rank = f"{r['rank']}위" if r.get("rank") is not None else "—"
        lines.append(f"| {rank} | **{_md(r.get('label', ''))}** | {fmt_score(r.get('score'))} | "
                     f"{r.get('entered_count', 0)}/{r.get('total_items', 0)} |")
    return "\n".join(lines)


def hidden_message(data: dict) -> str | None:
    n = sum(int(v or 0) for v in (data.get("hidden_count") or {}).values())
    return f"필터로 {n}건 숨김 · 남은 후보끼리 순위를 매겼습니다" if n > 0 else None
