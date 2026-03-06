from __future__ import annotations

import numpy as np
import pandas as pd


PURCHASE_EVENT_NAMES = {"af_purchase", "purchase", "in_app_purchase"}
LEVEL_TO_GROUP_COLS = {
    "media_source": ["media_source"],
    "campaign": ["media_source", "campaign"],
    "adset": ["media_source", "campaign", "adset"],
    "creative": ["media_source", "campaign", "adset", "creative"],
    "campaign_adset": ["campaign", "adset"],
}
CAMPAIGN_KEYS = ["media_source", "campaign"]


def _resolve_group_cols(level: str) -> list[str]:
    if level not in LEVEL_TO_GROUP_COLS:
        raise ValueError(f"Unsupported level: {level}")
    return LEVEL_TO_GROUP_COLS[level]


def _cohort_events(installs: pd.DataFrame, events: pd.DataFrame, max_day: int = 30) -> pd.DataFrame:
    dim_cols = [c for c in ["media_source", "campaign", "adset", "creative"] if c in installs.columns]
    merged = installs[["user_key", "install_time", *dim_cols]].merge(events, on="user_key", how="left")
    merged["day_diff"] = (merged["event_time"] - merged["install_time"]).dt.days
    return merged[merged["day_diff"].between(0, max_day, inclusive="both")].copy()


def _purchase_events(events: pd.DataFrame) -> pd.DataFrame:
    if "event_name" not in events.columns:
        return events.copy()
    names = events["event_name"].astype(str).str.lower()
    return events[names.isin(PURCHASE_EVENT_NAMES)].copy()


def _allocate_cost_by_level(installs: pd.DataFrame, cost: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    parent_keys = [k for k in CAMPAIGN_KEYS if k in group_cols]
    if not parent_keys:
        parent_keys = ["media_source"]

    cost_parent = cost.groupby(parent_keys, as_index=False).agg(
        spend=("spend", "sum"), impressions=("impressions", "sum"), clicks=("clicks", "sum")
    )

    if group_cols == parent_keys:
        return cost_parent

    install_counts = installs.groupby(group_cols, as_index=False).agg(installs=("user_key", "nunique"))
    parent_totals = install_counts.groupby(parent_keys, as_index=False).agg(parent_installs=("installs", "sum"))
    allocated = install_counts.merge(parent_totals, on=parent_keys, how="left").merge(
        cost_parent, on=parent_keys, how="left"
    )

    share = np.where(allocated["parent_installs"] > 0, allocated["installs"] / allocated["parent_installs"], 0)
    for col in ["spend", "impressions", "clicks"]:
        allocated[col] = allocated[col].fillna(0) * share

    return allocated[group_cols + ["spend", "impressions", "clicks"]]


def calculate_media_metrics(installs: pd.DataFrame, events: pd.DataFrame, cost: pd.DataFrame, level: str = "campaign") -> pd.DataFrame:
    group_cols = _resolve_group_cols(level)

    installs = installs.copy()
    installs["install_date"] = pd.to_datetime(installs["install_time"]).dt.date

    purchase_events = _purchase_events(events)
    cohort = _cohort_events(installs, purchase_events, max_day=30)

    install_agg = installs.groupby(group_cols, as_index=False).agg(installs=("user_key", "nunique"))

    rev = cohort.groupby(group_cols, as_index=False).agg(
        d1_revenue=("revenue", lambda s: s[cohort.loc[s.index, "day_diff"] <= 1].sum()),
        d7_revenue=("revenue", lambda s: s[cohort.loc[s.index, "day_diff"] <= 7].sum()),
        d30_revenue=("revenue", lambda s: s[cohort.loc[s.index, "day_diff"] <= 30].sum()),
        purchasers=("user_key", "nunique"),
        purchase_revenue=("revenue", "sum"),
    )

    cost_agg = _allocate_cost_by_level(installs, cost, group_cols)

    result = install_agg.merge(rev, on=group_cols, how="left").merge(cost_agg, on=group_cols, how="left")
    result = result.fillna(0)

    result["cpi"] = np.where(result["installs"] > 0, result["spend"] / result["installs"], np.nan)
    result["purchase_rate"] = np.where(result["installs"] > 0, result["purchasers"] / result["installs"], 0)
    result["arppu"] = np.where(result["purchasers"] > 0, result["purchase_revenue"] / result["purchasers"], 0)
    result["arpu"] = np.where(result["installs"] > 0, result["purchase_revenue"] / result["installs"], 0)
    result["d1_ltv"] = np.where(result["installs"] > 0, result["d1_revenue"] / result["installs"], 0)
    result["d7_ltv"] = np.where(result["installs"] > 0, result["d7_revenue"] / result["installs"], 0)
    result["d1_roas"] = np.where(result["spend"] > 0, result["d1_revenue"] / result["spend"], 0)
    result["d7_roas"] = np.where(result["spend"] > 0, result["d7_revenue"] / result["spend"], 0)

    daily_recovery = np.where(result["d7_revenue"] > 0, result["d7_revenue"] / 7.0, np.nan)
    result["payback_period_days"] = np.where(daily_recovery > 0, result["spend"] / daily_recovery, np.nan)

    return result.sort_values(group_cols).reset_index(drop=True)


def calculate_cohort_curve(installs: pd.DataFrame, events: pd.DataFrame, max_day: int = 30, level: str = "media_source") -> pd.DataFrame:
    group_cols = _resolve_group_cols(level)
    purchase_events = _purchase_events(events)
    cohort = _cohort_events(installs, purchase_events, max_day=max_day)
    install_counts = installs.groupby(group_cols)["user_key"].nunique().rename("installs").reset_index()

    rows = []
    for _, row in install_counts.iterrows():
        filt = np.ones(len(cohort), dtype=bool)
        for c in group_cols:
            filt &= cohort[c] == row[c]
        group = cohort[filt]
        installs_n = int(row["installs"])
        segment_label = " | ".join(str(row[c]) for c in group_cols)

        for day in range(1, max_day + 1):
            cum_revenue = group.loc[group["day_diff"] <= day, "revenue"].sum() if not group.empty else 0.0
            ltv = cum_revenue / installs_n if installs_n else 0
            rows.append({**{c: row[c] for c in group_cols}, "segment": segment_label, "day": day, "cum_revenue": cum_revenue, "ltv": ltv})

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# ROAS 분해: "CPI 문제냐, LTV 문제냐"
# ─────────────────────────────────────────────────────────────
def decompose_roas_change(
    metrics_current: pd.DataFrame,
    metrics_prev: pd.DataFrame,
    group_cols: list[str] | None = None,
) -> pd.DataFrame:
    """
    두 기간 사이의 D7 ROAS 변화를 CPI 기여분 / LTV 기여분으로 분해.

    수식 근거:
        ROAS = D7_LTV / CPI
        ΔROAS ≈ (ΔLTV / CPI_prev) - (LTV_prev × ΔCPI / CPI_prev²)

    반환 컬럼:
        roas_prev, roas_curr, roas_delta
        cpi_prev, cpi_curr, cpi_contribution  ← CPI 변화가 ROAS에 준 영향
        ltv_prev, ltv_curr, ltv_contribution  ← LTV 변화가 ROAS에 준 영향
        dominant_cause  ← "CPI 문제" / "LTV 문제" / "복합"
    """
    if group_cols is None:
        group_cols = ["media_source"]

    keep = group_cols + ["d7_roas", "cpi", "d7_ltv"]
    curr = metrics_current[keep].rename(columns={
        "d7_roas": "roas_curr", "cpi": "cpi_curr", "d7_ltv": "ltv_curr"
    })
    prev = metrics_prev[keep].rename(columns={
        "d7_roas": "roas_prev", "cpi": "cpi_prev", "d7_ltv": "ltv_prev"
    })

    df = curr.merge(prev, on=group_cols, how="inner")
    if df.empty:
        return df

    df["roas_delta"] = df["roas_curr"] - df["roas_prev"]

    # CPI 기여: CPI가 올라서 ROAS가 얼마나 빠졌나
    safe_cpi = df["cpi_prev"].clip(lower=1)
    df["cpi_contribution"] = -(df["ltv_prev"] * (df["cpi_curr"] - df["cpi_prev"]) / safe_cpi ** 2)

    # LTV 기여: LTV가 변해서 ROAS가 얼마나 달라졌나
    df["ltv_contribution"] = (df["ltv_curr"] - df["ltv_prev"]) / safe_cpi

    # 주요 원인 분류
    def _cause(row):
        cpi_c = abs(row["cpi_contribution"])
        ltv_c = abs(row["ltv_contribution"])
        if cpi_c == 0 and ltv_c == 0:
            return "변화 없음"
        ratio = cpi_c / (cpi_c + ltv_c) if (cpi_c + ltv_c) > 0 else 0.5
        if ratio >= 0.65:
            return "CPI 문제"
        if ratio <= 0.35:
            return "LTV 문제"
        return "복합 요인"

    df["dominant_cause"] = df.apply(_cause, axis=1)

    return df[group_cols + [
        "roas_prev", "roas_curr", "roas_delta",
        "cpi_prev", "cpi_curr", "cpi_contribution",
        "ltv_prev", "ltv_curr", "ltv_contribution",
        "dominant_cause",
    ]].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 코호트 성숙도 체크 (Attribution Lag 가드레일)
# ─────────────────────────────────────────────────────────────
def check_cohort_maturity(
    installs: pd.DataFrame,
    reference_date: pd.Timestamp | None = None,
    min_days: int = 7,
) -> pd.DataFrame:
    """
    D7 판단에 사용하기에 충분히 '익은' 코호트인지 확인.

    로직:
        install_date 기준으로 reference_date(기본: 데이터 마지막 날)까지
        경과 일수가 min_days 미만이면 IMMATURE 플래그.

    반환:
        install_date, cohort_age_days, is_mature, immature_installs, total_installs
    """
    if reference_date is None:
        reference_date = pd.to_datetime(installs["install_time"]).max()

    inst = installs.copy()
    inst["install_date"] = pd.to_datetime(inst["install_time"]).dt.normalize()
    inst["cohort_age_days"] = (reference_date - inst["install_date"]).dt.days
    inst["is_mature"] = inst["cohort_age_days"] >= min_days

    summary = inst.groupby("install_date").agg(
        total_installs   =("user_key",        "count"),
        cohort_age_days  =("cohort_age_days",  "first"),
        is_mature        =("is_mature",         "first"),
    ).reset_index()

    # 전체 요약
    total        = len(inst)
    immature_n   = int((~inst["is_mature"]).sum())
    immature_pct = immature_n / total * 100 if total > 0 else 0

    summary.attrs["immature_installs"]    = immature_n
    summary.attrs["immature_pct"]         = immature_pct
    summary.attrs["total_installs"]       = total
    summary.attrs["reference_date"]       = str(reference_date.date())
    summary.attrs["min_days"]             = min_days

    return summary
