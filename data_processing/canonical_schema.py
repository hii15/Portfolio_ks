from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

INSTALL_COLUMNS = [
    "user_key",
    "install_time",
    "media_source",
    "campaign",
    "adset",
    "creative",
    "geo",
    "platform",
]

EVENT_COLUMNS = ["user_key", "event_time", "event_name", "revenue", "revenue_currency"]

COST_COLUMNS = [
    "date", "media_source", "campaign", "adset", "creative",
    "impressions", "clicks", "spend", "spend_currency",
]


@dataclass
class CanonicalDataBundle:
    installs: pd.DataFrame
    events: pd.DataFrame
    cost: pd.DataFrame


def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = pd.NA
    return out[cols]


def coerce_canonical_types(installs: pd.DataFrame, events: pd.DataFrame, cost: pd.DataFrame) -> CanonicalDataBundle:
    installs = _ensure_columns(installs, INSTALL_COLUMNS)
    events = _ensure_columns(events, EVENT_COLUMNS)
    cost = _ensure_columns(cost, COST_COLUMNS)

    installs["install_time"] = pd.to_datetime(installs["install_time"], errors="coerce")
    events["event_time"] = pd.to_datetime(events["event_time"], errors="coerce")
    cost["date"] = pd.to_datetime(cost["date"], errors="coerce").dt.date

    events["revenue"] = pd.to_numeric(events["revenue"], errors="coerce").fillna(0.0)
    cost["impressions"] = pd.to_numeric(cost["impressions"], errors="coerce").fillna(0)
    cost["clicks"] = pd.to_numeric(cost["clicks"], errors="coerce").fillna(0)
    cost["spend"] = pd.to_numeric(cost["spend"], errors="coerce").fillna(0.0)

    # 빈 값은 추측하지 않는다. 통화가 불명확하면 UI에서 ROAS 판단을 보수적으로 제한한다.
    events["revenue_currency"] = events["revenue_currency"].fillna("UNKNOWN").astype(str).str.upper()
    cost["spend_currency"] = cost["spend_currency"].fillna("UNKNOWN").astype(str).str.upper()

    return CanonicalDataBundle(installs=installs, events=events, cost=cost)


def currency_alignment_status(bundle: CanonicalDataBundle) -> tuple[str, str]:
    """ROAS 계산에 필요한 매출/비용 통화의 정합성을 반환한다.

    status: aligned | unknown | mismatch | no_cost
    """
    if bundle.cost.empty or float(bundle.cost["spend"].sum()) <= 0:
        return "no_cost", "실제 광고비가 없어 ROAS 기반 판단을 제공하지 않습니다."

    revenue = set(bundle.events.loc[bundle.events["revenue"] != 0, "revenue_currency"].dropna())
    spend = set(bundle.cost.loc[bundle.cost["spend"] != 0, "spend_currency"].dropna())
    currencies = revenue | spend
    if not currencies or "UNKNOWN" in currencies:
        return "unknown", "매출 또는 비용 통화가 확인되지 않았습니다. ROAS는 참고용으로만 해석하세요."
    if len(revenue) != 1 or len(spend) != 1 or revenue != spend:
        return "mismatch", f"매출 통화({', '.join(sorted(revenue))})와 비용 통화({', '.join(sorted(spend))})가 일치하지 않습니다."
    currency = next(iter(revenue))
    return "aligned", f"매출·비용이 모두 {currency} 기준으로 정렬되었습니다."



def validate_canonical_bundle(bundle: CanonicalDataBundle) -> list[str]:
    detailed = validate_canonical_bundle_detailed(bundle)
    return [f"[{item['code']}] {item['message']}" for item in detailed]


VALIDATION_HELP_GUIDE = {
    "E001": "설치 데이터가 비어 있습니다. 설치 원본 파일을 다시 업로드해 주세요.",
    "E002": "설치시간 형식을 YYYY-MM-DD HH:MM:SS 형태로 맞춰 주세요.",
    "E003": "매체 컬럼명이 맞는지 확인해 주세요. (예: media_source)",
    "E004": "캠페인 컬럼명이 맞는지 확인해 주세요. (예: campaign)",
    "E005": "이벤트 데이터가 비어 있습니다. 이벤트 원본 파일을 다시 업로드해 주세요.",
    "E006": "이벤트시간 형식을 YYYY-MM-DD HH:MM:SS 형태로 맞춰 주세요.",
    "E007": "이벤트명 컬럼명이 맞는지 확인해 주세요. (예: event_name)",
}


def validate_canonical_bundle_detailed(bundle: CanonicalDataBundle) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def _push(code: str, message: str):
        issues.append({"code": code, "message": message, "guide": VALIDATION_HELP_GUIDE[code]})

    if bundle.installs.empty:
        _push("E001", "설치 데이터가 비어 있습니다.")
    else:
        if bundle.installs["install_time"].isna().all():
            _push("E002", "설치시간(install_time) 변환에 실패했습니다.")
        if bundle.installs["media_source"].isna().all():
            _push("E003", "매체(media_source) 정보가 없습니다.")
        if bundle.installs["campaign"].isna().all():
            _push("E004", "캠페인(campaign) 정보가 없습니다.")

    if bundle.events.empty:
        _push("E005", "이벤트 데이터가 비어 있습니다.")
    else:
        if bundle.events["event_time"].isna().all():
            _push("E006", "이벤트시간(event_time) 변환에 실패했습니다.")
        if bundle.events["event_name"].isna().all():
            _push("E007", "이벤트명(event_name) 정보가 없습니다.")

    return issues


def format_validation_issues(issues: list[dict[str, str]]) -> str:
    rows = ["업로드 데이터 점검이 필요합니다."]
    rows.extend([f"- [{i['code']}] {i['message']} → 해결: {i['guide']}" for i in issues])
    return "\n".join(rows)
