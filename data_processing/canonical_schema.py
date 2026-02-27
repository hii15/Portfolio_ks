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

EVENT_COLUMNS = ["user_key", "event_time", "event_name", "revenue"]

COST_COLUMNS = ["date", "media_source", "campaign", "impressions", "clicks", "spend"]


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

    return CanonicalDataBundle(installs=installs, events=events, cost=cost)



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
