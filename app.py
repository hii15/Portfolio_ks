from __future__ import annotations

import pandas as pd
import numpy as np
import streamlit as st

from data_processing.loader import load_file
from data_processing.adapters import ADAPTER_REGISTRY
from data_processing.canonical_schema import (
    coerce_canonical_types,
    format_validation_issues,
    validate_canonical_bundle_detailed,
)
from data_processing.metrics_engine import calculate_media_metrics, calculate_cohort_curve, decompose_roas_change, check_cohort_maturity
from data_processing.decision_engine import apply_decision_logic
from data_processing.liveops_analysis import compare_liveops_impact_by_level, derive_liveops_actions
from data_processing.raw_templates import get_raw_template_bundle
from dummy_data.generate_dummy_data import get_mmp_raw_bundle


# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(layout="wide", page_title="게임 UA 의사결정 콘솔")
st.title("🎮 게임 UA 의사결정 콘솔")
st.caption("MMP 원본 데이터를 기반으로 UA 집행 판단 · 예산 배분 · Cohort LTV · LiveOps 영향을 분석하는 인하우스 의사결정 도구")


# ─────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────
ANALYSIS_LEVEL_OPTIONS = ["media_source", "campaign", "adset", "creative"]
ANALYSIS_LEVEL_LABELS = {
    "media_source": "매체",
    "campaign":     "캠페인",
    "adset":        "광고그룹",
    "creative":     "소재",
}
DECISION_LABEL_MAP = {
    "Scale Up":          "⬆️ 증액",
    "Scale Down":        "⬇️ 감액",
    "Hold (Low Sample)": "⏸️ 보류(표본 부족)",
    "Maintain":          "✅ 유지",
}
EFFICIENCY_NOTE_MAP = {
    "Sample risk":       "⚠️ 표본 부족",
    "Strong efficiency": "🟢 효율 우수",
    "Efficiency risk":   "🔴 효율 저하",
    "Near target":       "🟡 목표 근접",
}
# (seed, label, phase)
# phase: "launch" = 사전예약~런칭기 (7~10억/월), "sustain" = 유지기 (1.5~3억/월)
DUMMY_SCENARIO_OPTIONS = [
    (11, "시나리오 1 · 런칭기 · 안정형 밸런스",      "launch"),
    (27, "시나리오 2 · 런칭기 · 고효율 매체 강세",    "launch"),
    (42, "시나리오 3 · 런칭기 · 기본 추천 시나리오",  "launch"),
    (58, "시나리오 4 · 유지기 · 효율 집중 운영",      "sustain"),
    (73, "시나리오 5 · 유지기 · 라이브옵스 반응 강화", "sustain"),
    (91, "시나리오 6 · 유지기 · 변동성 높은 혼합",    "sustain"),
]
DUMMY_LIVEOPS_START = "2026-01-15"
DUMMY_LIVEOPS_END   = "2026-01-21"
DATA_STATE_KEYS     = ["canonical", "raw_bundle"]


# ─────────────────────────────────────────────
# 앱 시작 시 기본 더미 데이터 자동 로딩 (최초 1회)
# ─────────────────────────────────────────────
if "canonical" not in st.session_state:
    try:
        _mmp = "AppsFlyer"
        _i, _e, _c = get_mmp_raw_bundle(mmp=_mmp, seed=42, phase="launch")
        _adapter   = ADAPTER_REGISTRY[_mmp]()
        _canonical = coerce_canonical_types(
            installs=_adapter.normalize_installs(_i),
            events=_adapter.normalize_events(_e),
            cost=_adapter.normalize_cost(_c),
        )
        st.session_state["canonical"]    = _canonical
        st.session_state["raw_bundle"]   = {"mmp": _mmp, "installs_raw": _i, "events_raw": _e, "cost_raw": _c}
        st.session_state["_auto_loaded"] = True
    except Exception:
        st.session_state["_auto_loaded"] = False


# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────
def _to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _empty_cost_template(installs: pd.DataFrame) -> pd.DataFrame:
    if installs.empty:
        return pd.DataFrame(columns=["date", "media_source", "campaign", "impressions", "clicks", "spend"])
    base = installs.copy()
    base["date"] = pd.to_datetime(base["install_time"], errors="coerce").dt.date
    grouped = base.groupby(["date", "media_source", "campaign"], as_index=False).agg(installs=("user_key", "count"))
    grouped["impressions"] = grouped["installs"] * 40
    grouped["clicks"]      = grouped["installs"] * 5
    grouped["spend"]       = grouped["installs"] * 3.0
    return grouped[["date", "media_source", "campaign", "impressions", "clicks", "spend"]]


def _normalize_uploaded_data(mmp, installs_raw, events_raw, cost_raw):
    adapter   = ADAPTER_REGISTRY[mmp]()
    installs  = adapter.normalize_installs(installs_raw)
    events    = adapter.normalize_events(events_raw)
    cost      = adapter.normalize_cost(cost_raw) if cost_raw is not None else pd.DataFrame()
    canonical = coerce_canonical_types(installs=installs, events=events, cost=cost)
    if canonical.cost.empty or canonical.cost["spend"].sum() == 0:
        canonical.cost = _empty_cost_template(canonical.installs)
    issues = validate_canonical_bundle_detailed(canonical)
    if issues:
        raise ValueError(format_validation_issues(issues))
    return canonical


def _set_loaded_bundle(canonical, raw_bundle: dict) -> None:
    st.session_state["canonical"]  = canonical
    st.session_state["raw_bundle"] = raw_bundle


def _friendly_decision_reason(reason: str) -> str:
    txt = str(reason)
    if "< min_installs" in txt:    return "표본 수가 최소 기준보다 작아 보수적으로 유지합니다."
    if "> upper_bound" in txt:     return "D7 ROAS가 상단 기준을 넘어 증액 후보입니다."
    if "< lower_bound" in txt:     return "D7 ROAS가 하단 기준보다 낮아 감액 후보입니다."
    if "<= d7_roas" in txt:        return "D7 ROAS가 목표 구간에 있어 유지 권장입니다."
    return txt


def _filter_by_period(installs: pd.DataFrame, period_days: int | None) -> pd.DataFrame:
    """period_days 기반 필터 — 내부 호환용으로 유지."""
    if period_days is None:
        return installs
    inst = installs.copy()
    inst["_d"] = pd.to_datetime(inst["install_time"]).dt.normalize()
    cutoff = inst["_d"].max() - pd.Timedelta(days=period_days - 1)
    return inst[inst["_d"] >= cutoff].drop(columns=["_d"])


def _filter_by_daterange(installs: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """날짜 범위(date 객체) 기반 필터."""
    inst = installs.copy()
    inst["_d"] = pd.to_datetime(inst["install_time"]).dt.normalize()
    cutoff_s = pd.Timestamp(start_date)
    cutoff_e = pd.Timestamp(end_date)
    return inst[(inst["_d"] >= cutoff_s) & (inst["_d"] <= cutoff_e)].drop(columns=["_d"])


def _date_slider(installs: pd.DataFrame, key: str):
    """
    데이터 기간 내에서 날짜 범위 슬라이더를 표시하고 (start, end) date 반환.
    데이터가 없으면 None, None 반환.
    """
    if installs.empty:
        return None, None
    dates = pd.to_datetime(installs["install_time"]).dt.normalize()
    min_d = dates.min().date()
    max_d = dates.max().date()
    if min_d == max_d:
        st.caption(f"📅 분석 기간: {min_d} (단일 날짜)")
        return min_d, max_d
    result = st.slider(
        "📅 분석 기간",
        min_value=min_d,
        max_value=max_d,
        value=(min_d, max_d),
        format="YYYY-MM-DD",
        key=key,
    )
    return result[0], result[1]


def _style_decision_table(df: pd.DataFrame):
    def row_color(row):
        decision  = str(row.get("판단", ""))
        styles    = [""] * len(row)
        col_names = list(row.index)
        if "증액" in decision:    bg = "background-color: #d4edda; color: #155724;"
        elif "감액" in decision:  bg = "background-color: #f8d7da; color: #721c24;"
        elif "보류" in decision:  bg = "background-color: #fff3cd; color: #856404;"
        else:                      bg = "background-color: #e8f4fd; color: #0c5460;"
        for i, col in enumerate(col_names):
            if col == "판단":
                styles[i] = bg
            elif col == "목표 대비 ROAS 차이(%)":
                v = row.get(col, 0)
                if isinstance(v, (int, float)):
                    if v >= 15:    styles[i] = "background-color: #c3e6cb; font-weight: bold;"
                    elif v <= -10: styles[i] = "background-color: #f5c6cb; font-weight: bold;"
            elif col == "효율 상태":
                note = str(row.get(col, ""))
                if "효율 우수" in note:  styles[i] = "color: #155724; font-weight: bold;"
                elif "효율 저하" in note: styles[i] = "color: #721c24; font-weight: bold;"
        return styles
    return df.style.apply(row_color, axis=1).format(
        {"목표 대비 ROAS 차이(%)": "{:.1f}%", "최소 설치수 대비 차이": "{:+.0f}"}, na_rep="-"
    )


def _show_data_period(canonical) -> None:
    """현재 로딩된 데이터의 기간을 작은 배지로 표시."""
    if canonical is None:
        return
    try:
        min_d = pd.to_datetime(canonical.installs["install_time"]).min().strftime("%Y-%m-%d")
        max_d = pd.to_datetime(canonical.installs["install_time"]).max().strftime("%Y-%m-%d")
        total_installs = len(canonical.installs)
        st.caption(f"📅 데이터 기간: **{min_d} ~ {max_d}** · 총 설치수: **{total_installs:,}명**")
    except Exception:
        pass


# ─────────────────────────────────────────────
# 예산 배분 계산 함수
# ─────────────────────────────────────────────
def _compute_media_roas_stats(installs, events, cost, bucket_days: int = 7) -> pd.DataFrame:
    """
    주간 버킷으로 매체별 D7 ROAS를 구해 평균·표준편차 계산.
    예상 ROAS 신뢰구간(±1σ) 산출 근거로 사용.
    """
    inst = installs.copy()
    inst["_d"] = pd.to_datetime(inst["install_time"]).dt.normalize()
    min_d, max_d = inst["_d"].min(), inst["_d"].max()

    buckets, current = [], min_d
    while current <= max_d:
        end_d        = current + pd.Timedelta(days=bucket_days - 1)
        bucket_inst  = inst[(inst["_d"] >= current) & (inst["_d"] <= end_d)].drop(columns=["_d"])
        if len(bucket_inst) >= 30:
            try:
                m = calculate_media_metrics(bucket_inst, events, cost, level="media_source")
                m["_bucket"] = str(current.date())
                buckets.append(m)
            except Exception:
                pass
        current = end_d + pd.Timedelta(days=1)

    # 버킷 분리 불가 시 단일 집계 폴백
    if not buckets:
        m = calculate_media_metrics(inst.drop(columns=["_d"], errors="ignore"), events, cost, level="media_source")
        return m[["media_source", "cpi", "d7_roas", "spend", "installs"]].rename(
            columns={"cpi": "cpi_mean", "d7_roas": "d7_roas_mean", "spend": "spend_total", "installs": "installs_total"}
        ).assign(d7_roas_std=0.0, cpi_std=0.0, bucket_count=1)

    all_m = pd.concat(buckets, ignore_index=True)
    stats = all_m.groupby("media_source", as_index=False).agg(
        cpi_mean       =("cpi",      "mean"),
        cpi_std        =("cpi",      "std"),
        d7_roas_mean   =("d7_roas",  "mean"),
        d7_roas_std    =("d7_roas",  "std"),
        spend_total    =("spend",    "sum"),
        installs_total =("installs", "sum"),
        bucket_count   =("_bucket",  "count"),
    )
    stats["d7_roas_std"] = stats["d7_roas_std"].fillna(0.0)
    stats["cpi_std"]     = stats["cpi_std"].fillna(0.0)
    return stats


def _allocate_budget(stats_df, total_budget, exclude_scale_down, decision_df, data_period_days) -> pd.DataFrame:
    df = stats_df.copy()

    if exclude_scale_down and decision_df is not None:
        sd_media = set(decision_df[decision_df["decision"] == "Scale Down"]["media_source"].tolist())
        df = df[~df["media_source"].isin(sd_media)].copy()

    if df.empty:
        return pd.DataFrame()

    df["_w"]          = df["d7_roas_mean"].clip(lower=0)
    total_w           = df["_w"].sum()
    df["배분 비중(%)"]  = (df["_w"] / total_w * 100).round(1) if total_w > 0 else 100.0 / len(df)
    df["추천 예산(원)"] = ((df["_w"] / total_w * total_budget).round(-3)).astype(int) if total_w > 0 else int(total_budget / len(df))

    df["예상 설치수"]        = (df["추천 예산(원)"] / df["cpi_mean"].clip(lower=1)).astype(int)
    df["예상 ROAS (하한)"]   = (df["d7_roas_mean"] - df["d7_roas_std"]).clip(lower=0).round(3)
    df["예상 ROAS (평균)"]   = df["d7_roas_mean"].round(3)
    df["예상 ROAS (상한)"]   = (df["d7_roas_mean"] + df["d7_roas_std"]).round(3)

    hist_spend = df["spend_total"] / df["bucket_count"] * (data_period_days / 7)
    df["과거 집행액(원)"]     = hist_spend.astype(int)
    df["_ratio"]             = df["추천 예산(원)"] / hist_spend.clip(lower=1)
    df["⚠️ 수확체감 주의"]   = df["_ratio"].apply(
        lambda r: "⚠️ 과거 대비 {:.0f}% 증액 — 실제 ROAS 하락 가능".format((r - 1) * 100) if r > 1.5 else "✅ 정상 범위"
    )

    return df[[
        "media_source", "배분 비중(%)", "추천 예산(원)", "과거 집행액(원)",
        "예상 설치수", "예상 ROAS (하한)", "예상 ROAS (평균)", "예상 ROAS (상한)", "⚠️ 수확체감 주의",
    ]].rename(columns={"media_source": "매체"}).reset_index(drop=True)


# ─────────────────────────────────────────────
# 탭 구성
# ─────────────────────────────────────────────
tab_upload, tab_decision, tab_budget, tab_curve, tab_liveops = st.tabs([
    "📂 데이터 업로드",
    "📊 UA 판단",
    "💰 예산 배분 추천",
    "📈 코호트 곡선",
    "🎉 라이브옵스 영향",
])


# ══════════════════════════════════════════════
# 탭 1 : 데이터 업로드
# ══════════════════════════════════════════════
with tab_upload:
    st.subheader("데이터 업로드")

    if st.session_state.get("_auto_loaded"):
        st.success("✅ 시나리오 3 기본 더미 데이터가 자동 로딩되었습니다. UA 판단 탭을 바로 확인해보세요!")

    # 더미 데이터는 AppsFlyer 고정 (MMP 선택 불필요)
    _DUMMY_MMP = "AppsFlyer"

    st.markdown("#### ⚡ 빠른 체험 — 더미 시나리오")
    st.caption("시드가 달라지면 매체 순위·성과가 완전히 달라집니다. 실무처럼 정해진 답이 없는 데이터입니다.")

    scenario_labels   = [label for _, label, _ in DUMMY_SCENARIO_OPTIONS]
    label_to_scenario = {label: (seed, phase) for seed, label, phase in DUMMY_SCENARIO_OPTIONS}
    q1, q2            = st.columns([1, 2])
    selected_label    = q1.selectbox("시나리오 선택", scenario_labels, index=2, key="upload_scenario")
    use_custom_seed   = q1.checkbox("시드 직접 입력 (고급)", value=False, key="upload_custom_seed")
    dummy_seed, dummy_phase = label_to_scenario[selected_label]
    if use_custom_seed:
        dummy_seed  = q1.number_input("시드 번호", min_value=0, value=int(dummy_seed), step=1, key="upload_seed_num")
        dummy_phase = q1.selectbox("단계", ["launch", "sustain"], key="upload_phase",
                                   help="launch=런칭기(7~10억/월), sustain=유지기(1.5~3억/월)")

    if q2.button("더미 데이터 불러오기", use_container_width=True):
        try:
            _i, _e, _c  = get_mmp_raw_bundle(mmp=_DUMMY_MMP, seed=int(dummy_seed), phase=dummy_phase)
            _canonical  = _normalize_uploaded_data(_DUMMY_MMP, _i, _e, _c)
            _set_loaded_bundle(_canonical, {"mmp": _DUMMY_MMP, "installs_raw": _i, "events_raw": _e, "cost_raw": _c})
            phase_label = "런칭기" if dummy_phase == "launch" else "유지기"
            st.success(f"더미 데이터 로드 완료 ({phase_label} · 시드: {int(dummy_seed)})")
            st.session_state["_auto_loaded"] = False
        except Exception as exc:
            st.error("더미 데이터 로드 중 오류가 발생했습니다.")
            st.code(str(exc))

    if st.button("🗑️ 데이터 초기화"):
        for k in DATA_STATE_KEYS + ["_auto_loaded"]:
            st.session_state.pop(k, None)
        st.success("초기화 완료")
        st.rerun()

    st.markdown("#### 📤 실제 데이터 업로드")
    st.caption("MMP에서 내보낸 Raw 데이터를 직접 업로드할 수 있습니다.")

    with st.expander("업로드 방법 안내", expanded=False):
        st.markdown("""
**지원 MMP**: AppsFlyer · Adjust · Singular

**필요 파일 3종**
- 설치 원본 (Install Raw)
- 이벤트 원본 (Event Raw)
- 비용 원본 (Cost Raw) — 선택사항

**업로드 오류 해결**
- **E001/E005**: 파일에 실제 데이터 행이 있는지 확인해 주세요.
- **E002/E006**: 시간 형식 오류 — `YYYY-MM-DD HH:MM:SS` 형태를 권장합니다.
- **E003/E004/E007**: 컬럼 누락 오류 — 아래 템플릿을 참고해 주세요.
""")
        st.markdown("**템플릿 다운로드**")
        mmp_for_tpl = st.selectbox("MMP 선택 (템플릿용)", ["AppsFlyer", "Adjust", "Singular"], key="tpl_mmp")
        t_i, t_e, t_c = get_raw_template_bundle(mmp_for_tpl)
        tc1, tc2, tc3 = st.columns(3)
        tc1.download_button("설치 템플릿 CSV",   data=_to_csv_bytes(t_i), file_name=f"{mmp_for_tpl.lower()}_installs_template.csv", mime="text/csv", use_container_width=True, key="dl_tpl_i")
        tc2.download_button("이벤트 템플릿 CSV", data=_to_csv_bytes(t_e), file_name=f"{mmp_for_tpl.lower()}_events_template.csv",  mime="text/csv", use_container_width=True, key="dl_tpl_e")
        tc3.download_button("비용 템플릿 CSV",   data=_to_csv_bytes(t_c), file_name=f"{mmp_for_tpl.lower()}_cost_template.csv",    mime="text/csv", use_container_width=True, key="dl_tpl_c")

    # MMP 선택은 실제 업로드 시에만 필요
    mmp_upload = st.selectbox(
        "사용 중인 MMP",
        ["AppsFlyer", "Adjust", "Singular"],
        key="upload_mmp",
        help="업로드할 파일의 출처 MMP를 선택하세요. 컬럼명 정규화에만 사용됩니다."
    )
    uc1, uc2, uc3 = st.columns(3)
    installs_file = uc1.file_uploader("설치 원본",        type=["csv", "xlsx"], key="installs")
    events_file   = uc2.file_uploader("이벤트 원본",      type=["csv", "xlsx"], key="events")
    cost_file     = uc3.file_uploader("비용 원본 (선택)", type=["csv", "xlsx"], key="cost")

    if installs_file and events_file:
        try:
            _i = load_file(installs_file)
            _e = load_file(events_file)
            _c = load_file(cost_file) if cost_file else None
            _canonical = _normalize_uploaded_data(mmp_upload, _i, _e, _c)
            _set_loaded_bundle(_canonical, {"mmp": mmp_upload, "installs_raw": _i, "events_raw": _e,
                                             "cost_raw": _c if _c is not None else pd.DataFrame()})
            st.success("정규화 완료")
            st.session_state["_auto_loaded"] = False
        except Exception as exc:
            st.error("데이터 정규화 중 오류가 발생했습니다.")
            st.code(str(exc))
    else:
        st.info("파일을 업로드하거나, 위의 더미 데이터 버튼을 눌러 주세요.")

    canonical_preview = st.session_state.get("canonical")
    if canonical_preview is not None:
        with st.expander("데이터 미리보기", expanded=False):
            st.caption("설치 데이터 (상위 10행)")
            st.dataframe(canonical_preview.installs.head(10), use_container_width=True)
            st.caption("이벤트 데이터 (상위 10행)")
            st.dataframe(canonical_preview.events.head(10), use_container_width=True)
            st.caption("비용 데이터 (상위 10행)")
            st.dataframe(canonical_preview.cost.head(10), use_container_width=True)

    raw_bundle = st.session_state.get("raw_bundle")
    if raw_bundle is not None:
        st.markdown("#### 원본 CSV 다운로드")
        raw_mmp = raw_bundle.get("mmp", "data")
        rd1, rd2, rd3 = st.columns(3)
        rd1.download_button("설치 원본 CSV",  data=_to_csv_bytes(raw_bundle.get("installs_raw", pd.DataFrame())), file_name=f"{raw_mmp.lower()}_install_raw.csv",  mime="text/csv", use_container_width=True, key="dl_raw_i")
        rd2.download_button("이벤트 원본 CSV", data=_to_csv_bytes(raw_bundle.get("events_raw",   pd.DataFrame())), file_name=f"{raw_mmp.lower()}_event_raw.csv",    mime="text/csv", use_container_width=True, key="dl_raw_e")
        rd3.download_button("비용 원본 CSV",  data=_to_csv_bytes(raw_bundle.get("cost_raw",      pd.DataFrame())), file_name=f"{raw_mmp.lower()}_cost_raw.csv",      mime="text/csv", use_container_width=True, key="dl_raw_c")


# 이후 탭 공통 변수
canonical = st.session_state.get("canonical")


# ══════════════════════════════════════════════
# 탭 2 : UA 판단
# ══════════════════════════════════════════════
with tab_decision:
    st.subheader("UA 판단")
    _show_data_period(st.session_state.get("canonical"))

    if canonical is None:
        st.warning("먼저 데이터 업로드 탭에서 데이터를 불러와 주세요.")
    else:
        st.caption("D7 ROAS = 설치 후 7일 누적 매출 ÷ 광고비 | Payback = 광고비 ÷ (D7매출 / 7일)")

        with st.expander("📖 용어 설명", expanded=False):
            st.markdown("""
| 용어 | 설명 |
|---|---|
| **판단** | 증액 / 감액 / 유지 / 보류 — D7 ROAS와 표본 수 기준으로 자동 분류 |
| **목표 대비 ROAS 차이(%)** | 양수 = 목표 초과(좋음), 음수 = 목표 미달(나쁨) |
| **Payback 기간** | 광고비를 매출로 회수하는 데 걸리는 예상 일수 |
| **효율 상태** | 성과를 4단계로 요약 (효율 우수 / 목표 근접 / 효율 저하 / 표본 부족) |
""")

        p1, p2, p3 = st.columns(3)
        decision_level = p1.selectbox("분석 레벨", ANALYSIS_LEVEL_OPTIONS, index=1, format_func=lambda x: ANALYSIS_LEVEL_LABELS[x], key="decision_level")
        target_roas    = p2.number_input("목표 ROAS", min_value=0.0, value=1.0, step=0.05, key="decision_target_roas")
        min_installs   = p3.number_input("최소 설치수 기준", min_value=1, value=200, step=10, key="decision_min_installs")

        # Geo 필터
        all_geos = sorted(canonical.installs["geo"].dropna().unique().tolist()) if "geo" in canonical.installs.columns else []
        if len(all_geos) > 1:
            sel_geos          = st.multiselect("🌏 국가(Geo) 필터", options=all_geos, default=all_geos, key="decision_geo")
            filtered_installs = canonical.installs[canonical.installs["geo"].isin(sel_geos)] if sel_geos else canonical.installs
        else:
            filtered_installs = canonical.installs

        d_start, d_end  = _date_slider(filtered_installs, key="decision_daterange")
        period_installs = _filter_by_daterange(filtered_installs, d_start, d_end) if d_start else filtered_installs
        if period_installs.empty:
            st.warning("선택한 기간에 데이터가 없습니다. 기간을 넓혀 주세요.")
        else:
            metrics     = calculate_media_metrics(period_installs, canonical.events, canonical.cost, level=decision_level)
            decision_df = apply_decision_logic(metrics, target_roas=target_roas, min_installs=int(min_installs))
            rank_map    = {"Scale Down": 0, "Hold (Low Sample)": 1, "Maintain": 2, "Scale Up": 3}
            decision_df = (
                decision_df
                .assign(_rank=decision_df["decision"].map(rank_map).fillna(99))
                .sort_values(["_rank", "roas_gap_vs_target_pct"])
                .drop(columns=["_rank"])
            )

            # 판단 요약 카드
            st.markdown("#### 📊 판단 요약")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("⬆️ 증액", int((decision_df["decision"] == "Scale Up").sum()))
            c2.metric("⬇️ 감액", int((decision_df["decision"] == "Scale Down").sum()))
            c3.metric("⏸️ 보류", int((decision_df["decision"] == "Hold (Low Sample)").sum()))
            c4.metric("✅ 유지", int((decision_df["decision"] == "Maintain").sum()))

            # Payback 카드
            if "payback_period_days" in decision_df.columns:
                valid_pb     = decision_df["payback_period_days"].dropna()
                scaleup_pb   = decision_df[decision_df["decision"] == "Scale Up"]["payback_period_days"].dropna()
                scaledown_pb = decision_df[decision_df["decision"] == "Scale Down"]["payback_period_days"].dropna()
                st.markdown("#### ⏱️ Payback Period")
                pb1, pb2, pb3, pb4 = st.columns(4)
                pb1.metric("전체 평균",      f"{valid_pb.mean():.1f}일"     if not valid_pb.empty else "-")
                pb2.metric("증액 후보 평균", f"{scaleup_pb.mean():.1f}일"   if not scaleup_pb.empty else "-",
                           delta=f"{scaleup_pb.mean() - valid_pb.mean():.1f}일" if not scaleup_pb.empty and not valid_pb.empty else None, delta_color="inverse")
                pb3.metric("감액 후보 평균", f"{scaledown_pb.mean():.1f}일" if not scaledown_pb.empty else "-",
                           delta=f"{scaledown_pb.mean() - valid_pb.mean():.1f}일" if not scaledown_pb.empty and not valid_pb.empty else None, delta_color="inverse")
                pb4.metric("최단 Payback",   f"{valid_pb.min():.1f}일"      if not valid_pb.empty else "-")

            # 경고 배지
            w1, w2 = st.columns(2)
            roas_risk_n   = int((decision_df["roas_gap_vs_target_pct"] <= -10).sum())
            sample_risk_n = int((decision_df["install_gap_to_min"] < 0).sum())
            if roas_risk_n:   w1.warning(f"🔴 ROAS 경고: {roas_risk_n}개 세그먼트 (목표 대비 -10% 이하)")
            if sample_risk_n: w2.warning(f"⚠️ 표본 부족: {sample_risk_n}개 세그먼트 (최소 설치수 미달)")

            # 메인 테이블
            st.markdown("#### 🗂️ 세그먼트별 상세 판단")

            CONFIDENCE_LABEL_MAP = {
                "높음": "🟢 높음",
                "보통": "🟡 보통",
                "낮음": "🔴 낮음",
            }

            decision_view = decision_df.copy()
            decision_view["decision"]        = decision_view["decision"].map(DECISION_LABEL_MAP).fillna(decision_view["decision"])
            decision_view["decision_reason"] = decision_view["decision_reason"]  # 이미 rich reason
            decision_view["efficiency_note"] = decision_view["efficiency_note"].apply(lambda x: EFFICIENCY_NOTE_MAP.get(str(x), str(x)))
            decision_view["confidence"]      = decision_view["confidence"].map(CONFIDENCE_LABEL_MAP).fillna(decision_view["confidence"])
            decision_view = decision_view.rename(columns={
                "decision":               "판단",
                "decision_reason":        "판단 사유",
                "action":                 "권장 액션",
                "confidence":             "신뢰도",
                "confidence_note":        "신뢰도 근거",
                "efficiency_note":        "효율 상태",
                "roas_gap_vs_target_pct": "목표 대비 ROAS 차이(%)",
                "install_gap_to_min":     "최소 설치수 대비 차이",
            })
            st.dataframe(_style_decision_table(decision_view), use_container_width=True, height=420)
            st.download_button("📥 판단 결과 CSV", data=_to_csv_bytes(decision_view),
                               file_name="ua_decision_table.csv", mime="text/csv",
                               use_container_width=True, key="dl_decision")

            # ── [NEW] 신뢰도 분포 요약 ──
            st.markdown("#### 🎯 신뢰도 분포")
            conf_counts = decision_df["confidence"].value_counts().to_dict()
            cf1, cf2, cf3 = st.columns(3)
            cf1.metric("🟢 높음", int(conf_counts.get("높음", 0)), help="설치수 ≥ 최소기준×3 + 구매자 ≥ 30명")
            cf2.metric("🟡 보통", int(conf_counts.get("보통", 0)), help="설치수 ≥ 최소기준 + 구매자 ≥ 10명")
            cf3.metric("🔴 낮음", int(conf_counts.get("낮음", 0)), help="표본 부족 — 판단 보수적으로 해석 필요")

            # ── [NEW] 코호트 성숙도 가드레일 ──
            st.markdown("#### 🕐 코호트 성숙도 체크 (Attribution Lag 가드레일)")
            maturity = check_cohort_maturity(period_installs, min_days=7)
            immature_n   = maturity.attrs.get("immature_installs", 0)
            immature_pct = maturity.attrs.get("immature_pct", 0.0)
            total_n      = maturity.attrs.get("total_installs", 0)
            ref_date     = maturity.attrs.get("reference_date", "-")

            if immature_pct > 20:
                st.warning(
                    f"⚠️ **D7 미성숙 코호트 비중 {immature_pct:.1f}%** ({immature_n:,}명 / 전체 {total_n:,}명) — "
                    f"설치 후 7일이 지나지 않은 유저가 포함되어 D7 ROAS가 **과소 추정**되었을 수 있습니다. "
                    f"기준일: {ref_date}"
                )
            elif immature_pct > 0:
                st.info(
                    f"ℹ️ D7 미성숙 코호트 {immature_pct:.1f}% ({immature_n:,}명) 포함 — "
                    f"비중이 낮아 판단에 미치는 영향은 제한적입니다."
                )
            else:
                st.success("✅ 모든 코호트가 D7 기준을 충족했습니다. ROAS 수치를 신뢰할 수 있습니다.")

            with st.expander("날짜별 코호트 성숙도 상세", expanded=False):
                maturity_view = maturity.rename(columns={
                    "install_date":    "설치일",
                    "cohort_age_days": "경과일",
                    "is_mature":       "D7 성숙 여부",
                    "total_installs":  "설치수",
                })
                maturity_view["D7 성숙 여부"] = maturity_view["D7 성숙 여부"].map({True: "✅ 성숙", False: "⚠️ 미성숙"})
                st.dataframe(maturity_view, use_container_width=True)

            # ── [NEW] ROAS 분해: CPI 문제 vs LTV 문제 ──
            st.markdown("#### 🔬 ROAS 분해 — CPI 문제인가, LTV 문제인가")
            st.caption("현재 기간 vs 직전 동일 길이 기간을 비교합니다. 기간이 충분하지 않으면 분해가 생략됩니다.")

            try:
                # 현재 기간과 동일한 길이의 직전 기간 자동 계산
                _curr_dates = pd.to_datetime(period_installs["install_time"]).dt.normalize()
                _curr_start = _curr_dates.min()
                _curr_end   = _curr_dates.max()
                _period_len = (_curr_end - _curr_start).days + 1
                _prev_end   = _curr_start - pd.Timedelta(days=1)
                _prev_start = _prev_end - pd.Timedelta(days=_period_len - 1)

                _prev_installs = _filter_by_daterange(
                    filtered_installs, _prev_start.date(), _prev_end.date()
                )

                if len(_prev_installs) < 100:
                    st.info("직전 기간 데이터가 부족해 ROAS 분해를 건너뜁니다. 분석 기간을 더 짧게 설정하면 비교가 가능해집니다.")
                else:
                    _grp = [c for c in ["media_source", "campaign"] if c in metrics.columns][:1]
                    _m_prev = calculate_media_metrics(_prev_installs, canonical.events, canonical.cost, level=decision_level)
                    decomp   = decompose_roas_change(metrics, _m_prev, group_cols=_grp)

                    if decomp.empty:
                        st.info("두 기간에 공통으로 집행된 세그먼트가 없어 분해를 건너뜁니다.")
                    else:
                        # 주요 원인별 색상
                        def _style_decomp(row):
                            cause = str(row.get("주요 원인", ""))
                            if "CPI" in cause:
                                return ["background-color: #fde8e8"] * len(row)
                            if "LTV" in cause:
                                return ["background-color: #e8f4fd"] * len(row)
                            if "복합" in cause:
                                return ["background-color: #fff3cd"] * len(row)
                            return [""] * len(row)

                        decomp_view = decomp.rename(columns={
                            "media_source":    "매체",
                            "roas_prev":       "이전 ROAS",
                            "roas_curr":       "현재 ROAS",
                            "roas_delta":      "ROAS 변화",
                            "cpi_prev":        "이전 CPI",
                            "cpi_curr":        "현재 CPI",
                            "cpi_contribution":"CPI 기여분",
                            "ltv_prev":        "이전 LTV",
                            "ltv_curr":        "현재 LTV",
                            "ltv_contribution":"LTV 기여분",
                            "dominant_cause":  "주요 원인",
                        })

                        # 원인별 요약 배지
                        cause_counts = decomp_view["주요 원인"].value_counts().to_dict()
                        dc1, dc2, dc3 = st.columns(3)
                        dc1.metric("🔴 CPI 문제",  int(cause_counts.get("CPI 문제",  0)), help="CPI 상승이 ROAS 하락의 주원인")
                        dc2.metric("🔵 LTV 문제",  int(cause_counts.get("LTV 문제",  0)), help="LTV 하락이 ROAS 하락의 주원인")
                        dc3.metric("🟡 복합 요인", int(cause_counts.get("복합 요인", 0)), help="CPI와 LTV 변화가 비슷한 비중으로 영향")

                        styled_decomp = decomp_view.style.apply(_style_decomp, axis=1).format({
                            "이전 ROAS": "{:.3f}", "현재 ROAS": "{:.3f}", "ROAS 변화": "{:+.3f}",
                            "이전 CPI":  "{:,.0f}", "현재 CPI":  "{:,.0f}",
                            "CPI 기여분":"{:+.3f}",
                            "이전 LTV":  "{:,.0f}", "현재 LTV":  "{:,.0f}",
                            "LTV 기여분":"{:+.3f}",
                        }, na_rep="-")
                        st.dataframe(styled_decomp, use_container_width=True)
                        st.caption("🔴 빨간 행 = CPI 문제 · 🔵 파란 행 = LTV 문제 · 🟡 노란 행 = 복합 요인")

            except Exception as _e:
                st.info(f"ROAS 분해를 계산할 수 없습니다: {_e}")


# ══════════════════════════════════════════════
# 탭 3 : 예산 배분 추천
# ══════════════════════════════════════════════
with tab_budget:
    st.subheader("💰 예산 배분 추천")
    _show_data_period(st.session_state.get("canonical"))

    if canonical is None:
        st.warning("먼저 데이터 업로드 탭에서 데이터를 불러와 주세요.")
    else:
        st.caption("D7 ROAS 비중 기반 배분 | 예상 ROAS = 과거 주간 평균 ± 1σ (표준편차)")

        with st.expander("📖 산출 근거 및 한계", expanded=False):
            st.markdown("""
**예상 설치수** = 추천 예산 ÷ 과거 평균 CPI
- 과거 CPI가 유지된다는 가정입니다. 실제 경쟁 환경에 따라 달라질 수 있습니다.

**예상 ROAS 범위 (하한 ~ 상한)** = 과거 주간 D7 ROAS 평균 ± 표준편차(1σ)
- 주간 버킷이 많을수록 더 신뢰할 수 있습니다. 신뢰구간이 넓을수록 불확실성이 높습니다.

**⚠️ 수확체감 주의** = 추천 예산이 과거 동기간 집행액의 1.5배 초과 시 표시
- 예산을 대폭 늘리면 오디언스 소진으로 실제 ROAS가 예상보다 낮아질 수 있습니다.
""")

        b1, b2 = st.columns(2)
        total_budget = b1.number_input("다음 달 총 예산 (원)", min_value=100_000, value=50_000_000, step=1_000_000, format="%d", key="budget_total")
        exclude_sd   = b2.checkbox("감액 판단 매체 배분 제외", value=True, key="budget_exclude_sd",
                                    help="UA 판단에서 감액 판정된 매체는 배분에서 제외합니다")

        # Geo 필터
        all_geos_b = sorted(canonical.installs["geo"].dropna().unique().tolist()) if "geo" in canonical.installs.columns else []
        if len(all_geos_b) > 1:
            sel_geos_b      = st.multiselect("🌏 국가 필터", options=all_geos_b, default=all_geos_b, key="budget_geo")
            budget_installs = canonical.installs[canonical.installs["geo"].isin(sel_geos_b)] if sel_geos_b else canonical.installs
        else:
            budget_installs = canonical.installs

        b_start, b_end    = _date_slider(budget_installs, key="budget_daterange")
        period_installs_b = _filter_by_daterange(budget_installs, b_start, b_end) if b_start else budget_installs
        budget_period_days = (pd.Timestamp(b_end) - pd.Timestamp(b_start)).days + 1 if b_start else 30

        # 감액 판단 참조용
        budget_metrics  = calculate_media_metrics(period_installs_b, canonical.events, canonical.cost, level="media_source")
        budget_decision = apply_decision_logic(budget_metrics, target_roas=1.0, min_installs=200)

        with st.spinner("주간 ROAS 통계 계산 중..."):
            stats_df = _compute_media_roas_stats(period_installs_b, canonical.events, canonical.cost, bucket_days=7)

        alloc_df = _allocate_budget(stats_df, float(total_budget), exclude_sd, budget_decision, budget_period_days)

        if alloc_df.empty:
            st.warning("배분 가능한 매체가 없습니다. '감액 판단 매체 배분 제외' 옵션을 해제해 보세요.")
        else:
            # 총계 요약
            s1, s2, s3 = st.columns(3)
            s1.metric("총 배분 예산",   f"{alloc_df['추천 예산(원)'].sum():,.0f}원")
            s2.metric("총 예상 설치수", f"{alloc_df['예상 설치수'].sum():,}명")
            s3.metric("예상 ROAS 범위", f"{alloc_df['예상 ROAS (하한)'].mean():.2f} ~ {alloc_df['예상 ROAS (상한)'].mean():.2f}")

            # 배분 차트
            st.markdown("#### 매체별 추천 예산 배분")
            chart_df = alloc_df.set_index("매체")[["추천 예산(원)"]].sort_values("추천 예산(원)", ascending=False)
            st.bar_chart(chart_df)

            # 상세 테이블
            st.markdown("#### 상세 배분 테이블")

            def highlight_warning(row):
                return ["background-color: #fff3cd"] * len(row) if "⚠️" in str(row.get("⚠️ 수확체감 주의", "")) else [""] * len(row)

            styled_alloc = alloc_df.style.apply(highlight_warning, axis=1).format({
                "배분 비중(%)":      "{:.1f}%",
                "추천 예산(원)":     "{:,.0f}",
                "과거 집행액(원)":   "{:,.0f}",
                "예상 설치수":       "{:,}",
                "예상 ROAS (하한)": "{:.3f}",
                "예상 ROAS (평균)": "{:.3f}",
                "예상 ROAS (상한)": "{:.3f}",
            })
            st.dataframe(styled_alloc, use_container_width=True)
            st.caption("※ 노란색 행: 추천 예산이 과거 집행액 대비 1.5배 초과 → 실제 ROAS는 낮아질 수 있습니다.")
            st.download_button("📥 예산 배분 CSV", data=_to_csv_bytes(alloc_df),
                               file_name="budget_allocation.csv", mime="text/csv",
                               use_container_width=True, key="dl_budget")


# ══════════════════════════════════════════════
# 탭 4 : 코호트 곡선
# ══════════════════════════════════════════════
with tab_curve:
    st.subheader("코호트 곡선")
    _show_data_period(st.session_state.get("canonical"))

    if canonical is None:
        st.warning("먼저 데이터 업로드 탭에서 데이터를 불러와 주세요.")
    else:
        st.caption("D일 누적 LTV = 설치 후 D일 이내 누적 매출 ÷ 설치수")

        curve_level = st.selectbox("분석 레벨", ANALYSIS_LEVEL_OPTIONS, index=0, format_func=lambda x: ANALYSIS_LEVEL_LABELS[x], key="curve_level")
        c_start, c_end = _date_slider(canonical.installs, key="curve_daterange")
        curve_installs = _filter_by_daterange(canonical.installs, c_start, c_end) if c_start else canonical.installs
        curve          = calculate_cohort_curve(curve_installs, canonical.events, max_day=30, level=curve_level)

        if curve.empty:
            st.info("곡선을 계산할 데이터가 없습니다.")
        else:
            segments         = sorted(curve["segment"].unique().tolist())
            default_segments = segments[:min(8, len(segments))]
            selected         = st.multiselect("세그먼트 선택", segments, default=default_segments, key="curve_segments")
            view             = curve[curve["segment"].isin(selected)]

            if view.empty:
                st.info("선택한 세그먼트에 해당하는 데이터가 없습니다.")
            else:
                d7_rank = view[view["day"] == 7].sort_values("ltv", ascending=False)
                if not d7_rank.empty:
                    st.markdown("#### D7 LTV 순위")
                    rank_cols = st.columns(min(4, len(d7_rank)))
                    medals    = ["🥇", "🥈", "🥉", "4️⃣"]
                    for i, (_, row) in enumerate(d7_rank.head(4).iterrows()):
                        rank_cols[i].metric(f"{medals[i]} {row['segment']}", f"{row['ltv']:.2f}")

                st.line_chart(view, x="day", y="ltv", color="segment")
                st.download_button("📥 코호트 곡선 CSV", data=_to_csv_bytes(view),
                                   file_name="cohort_curve.csv", mime="text/csv",
                                   use_container_width=True, key="dl_curve")


# ══════════════════════════════════════════════
# 탭 5 : 라이브옵스 영향
# ══════════════════════════════════════════════
with tab_liveops:
    st.subheader("라이브옵스 영향")
    _show_data_period(st.session_state.get("canonical"))

    if canonical is None:
        st.warning("먼저 데이터 업로드 탭에서 데이터를 불러와 주세요.")
    else:
        st.caption("라이브옵스 영향 = 이벤트 기간 D7 LTV − 비교 기간 D7 LTV")

        st.info(
            f"💡 더미 데이터 라이브옵스 이벤트 기간: "
            f"**{DUMMY_LIVEOPS_START} ~ {DUMMY_LIVEOPS_END}** "
            f"→ 아래 버튼으로 자동 입력하세요."
        )
        if st.button("📅 권장 날짜 자동 입력"):
            st.session_state["lo_start"] = DUMMY_LIVEOPS_START
            st.session_state["lo_end"]   = DUMMY_LIVEOPS_END

        default_start = pd.to_datetime(st.session_state.get("lo_start", DUMMY_LIVEOPS_START)).date()
        default_end   = pd.to_datetime(st.session_state.get("lo_end",   DUMMY_LIVEOPS_END)).date()

        col1, col2, col3, col4 = st.columns(4)
        lo_start      = col1.date_input("이벤트 시작일", value=default_start, key="liveops_start")
        lo_end        = col2.date_input("이벤트 종료일", value=default_end, key="liveops_end")
        baseline_days = col3.number_input("비교 기간(일)", min_value=1, value=7, step=1, key="liveops_baseline")
        liveops_level = col4.selectbox("분석 레벨", ANALYSIS_LEVEL_OPTIONS, index=0, format_func=lambda x: ANALYSIS_LEVEL_LABELS[x], key="liveops_level")
        min_sample    = st.number_input("최소 표본수 필터", min_value=0, value=100, step=10, key="liveops_min_sample")

        if lo_start > lo_end:
            st.error("시작일은 종료일보다 늦을 수 없습니다.")
        else:
            impact_df = compare_liveops_impact_by_level(
                canonical.installs, canonical.events,
                event_start=str(lo_start), event_end=str(lo_end),
                baseline_days=int(baseline_days), level=liveops_level,
            )
            filtered = impact_df[
                (impact_df["liveops_sample"] >= int(min_sample)) |
                (impact_df["baseline_sample"] >= int(min_sample))
            ].copy()

            if filtered.empty:
                st.warning("비교 가능한 데이터가 없습니다.")
                st.markdown(f"""
**해결 방법**
1. 이벤트 기간을 더 넓혀 보세요 (현재 `{lo_start}` ~ `{lo_end}`)
2. 분석 레벨을 더 상위(매체/캠페인)로 바꿔 보세요
3. 최소 표본수 필터(`{int(min_sample)}`)를 낮춰 보세요
4. 더미 데이터라면 위 '권장 날짜 자동 입력' 버튼을 눌러 주세요
""")
            else:
                top_seg    = filtered.nlargest(1, "impact").iloc[0]
                bottom_seg = filtered.nsmallest(1, "impact").iloc[0]

                lv1, lv2, lv3, lv4 = st.columns(4)
                lv1.metric("평균 D7 LTV 상승",    f"{filtered['impact'].mean():.4f}")
                lv2.metric("최대 상승 세그먼트",   top_seg["segment"],    delta=f"ΔLTV {top_seg['impact']:.2f}")
                lv3.metric("최소 상승 세그먼트",   bottom_seg["segment"], delta=f"ΔLTV {bottom_seg['impact']:.2f}", delta_color="inverse")
                lv4.metric("비교 세그먼트 수",     len(filtered))

                st.markdown("#### 매체별 라이브옵스 영향 요약")
                cards = filtered.groupby("media_source", as_index=False).agg(
                    평균_ΔLTV =("impact",        "mean"),
                    세그먼트수 =("segment",       "count"),
                    총_표본   =("liveops_sample", "sum"),
                ).sort_values("평균_ΔLTV", ascending=False)
                st.dataframe(cards, use_container_width=True)

                actionable    = derive_liveops_actions(filtered, min_sample=int(min_sample))
                action_counts = actionable["action_label"].value_counts().to_dict()
                a1, a2, a3 = st.columns(3)
                a1.metric("⬆️ 증액 후보",      int(action_counts.get("증액 후보", 0)))
                a2.metric("🔻 점검/감액 후보",  int(action_counts.get("점검/감액 후보", 0)))
                a3.metric("⏸️ 보류(표본 부족)", int(action_counts.get("보류(표본 부족)", 0)))

                st.markdown("#### 레벨별 라이브옵스 영향 + 운영 액션")
                st.dataframe(actionable, use_container_width=True)
                st.download_button("📥 라이브옵스 결과 CSV", data=_to_csv_bytes(actionable),
                                   file_name="liveops_impact.csv", mime="text/csv",
                                   use_container_width=True, key="dl_liveops")
