from __future__ import annotations

import pandas as pd

from data_processing.metrics_engine import PURCHASE_EVENT_NAMES


def _resolve_group_cols(level: str) -> list[str]:
    level_map = {
        "media_source": ["media_source"],
        "campaign": ["media_source", "campaign"],
        "adset": ["media_source", "campaign", "adset"],
        "creative": ["media_source", "campaign", "adset", "creative"],
        "campaign_adset": ["campaign", "adset"],
    }
    if level not in level_map:
        raise ValueError(f"Unsupported level: {level}")
    return level_map[level]


def _purchase_events_only(events: pd.DataFrame) -> pd.DataFrame:
    names = events["event_name"].astype(str).str.lower() if "event_name" in events.columns else None
    return events[names.isin(PURCHASE_EVENT_NAMES)].copy() if names is not None else events.copy()


def _d7_ltv_by_group(cohort: pd.DataFrame, purchase_events: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if cohort.empty:
        return pd.DataFrame(columns=group_cols + ["d7_ltv", "sample"])

    merged = cohort[["user_key", "install_time", *group_cols]].merge(purchase_events, on="user_key", how="left")
    merged["day_diff"] = (merged["event_time"] - merged["install_time"]).dt.days

    installs_agg = cohort.groupby(group_cols, as_index=False).agg(sample=("user_key", "nunique"))
    rev_agg = merged[merged["day_diff"].between(0, 7, inclusive="both")].groupby(group_cols, as_index=False).agg(
        d7_revenue=("revenue", "sum")
    )
    out = installs_agg.merge(rev_agg, on=group_cols, how="left").fillna({"d7_revenue": 0.0})
    out["d7_ltv"] = out["d7_revenue"] / out["sample"].where(out["sample"] > 0, 1)
    return out[group_cols + ["d7_ltv", "sample"]]


def compare_liveops_impact_by_level(
    installs: pd.DataFrame,
    events: pd.DataFrame,
    event_start: str,
    event_end: str,
    baseline_days: int | None = None,
    level: str = "media_source",
) -> pd.DataFrame:
    installs = installs.copy()
    installs["install_date"] = pd.to_datetime(installs["install_time"]).dt.date
    event_start_dt = pd.to_datetime(event_start).date()
    event_end_dt = pd.to_datetime(event_end).date()

    group_cols = _resolve_group_cols(level)
    purchase_events = _purchase_events_only(events)

    liveops = installs[installs["install_date"].between(event_start_dt, event_end_dt)]

    duration = (event_end_dt - event_start_dt).days + 1
    baseline_days = baseline_days or duration
    baseline_end = event_start_dt - pd.Timedelta(days=1)
    baseline_start = baseline_end - pd.Timedelta(days=baseline_days - 1)
    baseline = installs[installs["install_date"].between(baseline_start, baseline_end)]

    liveops_ltv = _d7_ltv_by_group(liveops, purchase_events, group_cols).rename(
        columns={"d7_ltv": "liveops_d7_ltv", "sample": "liveops_sample"}
    )
    baseline_ltv = _d7_ltv_by_group(baseline, purchase_events, group_cols).rename(
        columns={"d7_ltv": "baseline_d7_ltv", "sample": "baseline_sample"}
    )

    out = liveops_ltv.merge(baseline_ltv, on=group_cols, how="outer")
    for col in ["liveops_d7_ltv", "baseline_d7_ltv", "liveops_sample", "baseline_sample"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    out["impact"] = out["liveops_d7_ltv"] - out["baseline_d7_ltv"]
    out["event_start"] = event_start_dt
    out["event_end"] = event_end_dt
    out["baseline_start"] = baseline_start
    out["baseline_end"] = baseline_end
    if out.empty:
        out["segment"] = pd.Series(dtype="object")
    else:
        out["segment"] = out[group_cols].fillna("(없음)").astype(str).agg(" | ".join, axis=1)
    return out[
        [
            *group_cols,
            "segment",
            "event_start",
            "event_end",
            "baseline_start",
            "baseline_end",
            "liveops_d7_ltv",
            "baseline_d7_ltv",
            "impact",
            "liveops_sample",
            "baseline_sample",
        ]
    ].sort_values("impact", ascending=False).reset_index(drop=True)


def derive_liveops_actions(
    impact_df: pd.DataFrame,
    min_sample: int = 100,
    positive_threshold: float = 0.20,
    negative_threshold: float = -0.20,
) -> pd.DataFrame:
    out = impact_df.copy()
    if out.empty:
        out["impact_pct"] = pd.Series(dtype="float")
        out["action_label"] = pd.Series(dtype="object")
        out["action_priority"] = pd.Series(dtype="int")
        out["action_note"] = pd.Series(dtype="object")
        return out

    sample_floor = out[["liveops_sample", "baseline_sample"]].min(axis=1)
    safe_baseline = out["baseline_d7_ltv"].where(out["baseline_d7_ltv"].abs() > 0, pd.NA)
    out["impact_pct"] = (out["impact"] / safe_baseline).fillna(0.0)

    is_low_sample = sample_floor < int(min_sample)
    is_positive = (out["impact_pct"] >= positive_threshold) & (out["impact"] > 0)
    is_negative = (out["impact_pct"] <= negative_threshold) & (out["impact"] < 0)

    out["action_label"] = "관찰 유지"
    out.loc[is_positive, "action_label"] = "증액 후보"
    out.loc[is_negative, "action_label"] = "점검/감액 후보"
    out.loc[is_low_sample, "action_label"] = "보류(표본 부족)"

    out["action_priority"] = 2
    out.loc[out["action_label"].isin(["증액 후보", "점검/감액 후보"]), "action_priority"] = 1
    out.loc[out["action_label"] == "보류(표본 부족)", "action_priority"] = 3

    out["action_note"] = "추세 관찰 후 다음 구간에서 재확인"
    out.loc[out["action_label"] == "증액 후보", "action_note"] = "이벤트 시기 효율 상승 구간으로 예산 확대 테스트"
    out.loc[out["action_label"] == "점검/감액 후보", "action_note"] = "크리에이티브/랜딩/타겟 점검 후 보수적으로 운영"
    out.loc[out["action_label"] == "보류(표본 부족)", "action_note"] = "표본이 적어 성급한 판단 대신 데이터 추가 확보 필요"

    return out


def compare_liveops_impact(
    installs: pd.DataFrame,
    events: pd.DataFrame,
    event_start: str,
    event_end: str,
    baseline_days: int | None = None,
) -> pd.DataFrame:
    out = compare_liveops_impact_by_level(
        installs=installs,
        events=events,
        event_start=event_start,
        event_end=event_end,
        baseline_days=baseline_days,
        level="media_source",
    )
    if out.empty:
        return pd.DataFrame(
            {
                "event_start": [pd.to_datetime(event_start).date()],
                "event_end": [pd.to_datetime(event_end).date()],
                "baseline_start": [pd.to_datetime(event_start).date()],
                "baseline_end": [pd.to_datetime(event_end).date()],
                "liveops_d7_ltv": [0.0],
                "baseline_d7_ltv": [0.0],
                "impact": [0.0],
                "liveops_sample": [0],
                "baseline_sample": [0],
            }
        )

    summary = {
        "event_start": out.loc[0, "event_start"],
        "event_end": out.loc[0, "event_end"],
        "baseline_start": out.loc[0, "baseline_start"],
        "baseline_end": out.loc[0, "baseline_end"],
        "liveops_d7_ltv": out["liveops_d7_ltv"].mean(),
        "baseline_d7_ltv": out["baseline_d7_ltv"].mean(),
        "impact": out["impact"].mean(),
        "liveops_sample": int(out["liveops_sample"].sum()),
        "baseline_sample": int(out["baseline_sample"].sum()),
    }
    return pd.DataFrame([summary])
