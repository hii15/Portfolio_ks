from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────
# Action 맵핑
# Scale Up   → 예산 증액 + 소재 확대
# Scale Down → 예산 감액 (원인에 따라 세분화)
# Hold       → 추가 데이터 수집 대기
# Maintain   → 현 상태 유지
# ─────────────────────────────────────────────────────────────
def _recommend_action(decision: str, row: pd.Series, target_roas: float) -> str:
    d7_roas   = float(row.get("d7_roas",  0.0))
    cpi       = float(row.get("cpi",      0.0))
    d7_ltv    = float(row.get("d7_ltv",   0.0))
    installs  = int(row.get("installs",   0))
    purchasers= int(row.get("purchasers", 0))

    if decision == "Hold (Low Sample)":
        return "예산 유지 후 표본 확보 대기 (최소 설치수 충족 시 재판단)"

    if decision == "Scale Up":
        roas_gap = (d7_roas - target_roas) / target_roas
        if roas_gap >= 0.5:
            return "예산 +30~50% 증액 · 소재 물량 확대 · 입찰가 +10% 검토"
        return "예산 +15~25% 증액 · 현 소재 유지 · 주간 단위 모니터링"

    if decision == "Scale Down":
        # 원인 분해: CPI 문제 vs LTV 문제
        # CPI 문제: CPI가 LTV 대비 너무 높음 (CPI > d7_ltv * 0.8)
        # LTV 문제: 구매전환율이 낮음 (purchasers/installs < 5%)
        purchase_rate = purchasers / installs if installs > 0 else 0
        if cpi > d7_ltv * 0.8 and purchase_rate >= 0.05:
            return "입찰가 -10~15% 인하 · CPI 개선 우선 · 소재 교체 검토"
        if purchase_rate < 0.05:
            return "소재 전면 교체 · 타겟 오디언스 재검토 · CVR 개선 집중"
        gap_pct = abs(d7_roas - target_roas) / target_roas
        if gap_pct >= 0.4:
            return "예산 -30~40% 감축 · 해당 매체 최소화 운영 유지"
        return "예산 -15~20% 감축 · 소재 A/B 테스트 병행"

    # Maintain
    return "현 예산 유지 · 소재 성과 모니터링 지속"


def _confidence_level(installs: int, purchasers: int, min_installs: int) -> tuple[str, str]:
    """
    신뢰도 = 표본 크기 기반.
    - 높음: min_installs × 3 이상 + 구매자 30명 이상
    - 보통: min_installs 이상 + 구매자 10명 이상
    - 낮음: 나머지
    반환: (level, reason)
    """
    if installs >= min_installs * 3 and purchasers >= 30:
        return ("높음", f"설치 {installs:,}명 · 구매자 {purchasers}명 — 충분한 표본")
    if installs >= min_installs and purchasers >= 10:
        return ("보통", f"설치 {installs:,}명 · 구매자 {purchasers}명 — 기준 충족")
    return ("낮음", f"설치 {installs:,}명 · 구매자 {purchasers}명 — 추가 데이터 필요")


def _rich_reason(decision: str, row: pd.Series, target_roas: float,
                 lower: float, upper: float, min_installs: int) -> str:
    """사람이 읽을 수 있는 판단 사유."""
    d7_roas    = float(row.get("d7_roas",  0.0))
    cpi        = float(row.get("cpi",      0.0))
    d7_ltv     = float(row.get("d7_ltv",   0.0))
    installs   = int(row.get("installs",   0))
    purchasers = int(row.get("purchasers", 0))
    purchase_rate = purchasers / installs if installs > 0 else 0

    if decision == "Hold (Low Sample)":
        return f"설치수 {installs:,}명으로 최소 기준({min_installs:,}명) 미달 — 데이터 누적 후 재판단 필요"

    if decision == "Scale Up":
        gap = (d7_roas - target_roas) / target_roas * 100
        return (f"D7 ROAS {d7_roas:.3f}로 목표({target_roas:.1f}) 대비 +{gap:.1f}% 초과 달성 · "
                f"CPI {cpi:,.0f}원 / D7 LTV {d7_ltv:,.0f}원 — 효율 우수")

    if decision == "Scale Down":
        gap = (d7_roas - target_roas) / target_roas * 100
        # 원인 분류
        if cpi > d7_ltv * 0.8 and purchase_rate >= 0.05:
            cause = f"CPI({cpi:,.0f}원)가 D7 LTV({d7_ltv:,.0f}원) 대비 과도 — CPI 문제"
        elif purchase_rate < 0.05:
            cause = f"구매전환율 {purchase_rate*100:.1f}% — CVR 문제 (소재/타겟)"
        else:
            cause = f"D7 LTV({d7_ltv:,.0f}원) 낮음 — 유저 품질 문제"
        return f"D7 ROAS {d7_roas:.3f}로 목표 대비 {gap:.1f}% 미달 · {cause}"

    # Maintain
    return (f"D7 ROAS {d7_roas:.3f}로 목표 구간({lower:.2f}~{upper:.2f}) 내 — "
            f"CPI {cpi:,.0f}원 / D7 LTV {d7_ltv:,.0f}원")


def apply_decision_logic(
    metrics_df: pd.DataFrame,
    target_roas: float,
    min_installs: int = 200,
    upper_buffer: float = 1.15,
    lower_buffer: float = 0.90,
) -> pd.DataFrame:
    out = metrics_df.copy()
    upper = target_roas * upper_buffer
    lower = target_roas * lower_buffer

    decisions, reasons, actions, conf_levels, conf_reasons = [], [], [], [], []

    for _, row in out.iterrows():
        installs   = int(row.get("installs",   0))
        purchasers = int(row.get("purchasers", 0))
        d7_roas    = float(row.get("d7_roas",  0.0))

        # ── 판단 ──
        if installs < min_installs:
            decision = "Hold (Low Sample)"
        elif d7_roas > upper:
            decision = "Scale Up"
        elif d7_roas < lower:
            decision = "Scale Down"
        else:
            decision = "Maintain"

        # ── 상세 사유 / 액션 / 신뢰도 ──
        reason   = _rich_reason(decision, row, target_roas, lower, upper, min_installs)
        action   = _recommend_action(decision, row, target_roas)
        conf, cr = _confidence_level(installs, purchasers, min_installs)

        decisions.append(decision)
        reasons.append(reason)
        actions.append(action)
        conf_levels.append(conf)
        conf_reasons.append(cr)

    out["decision"]        = decisions
    out["decision_reason"] = reasons
    out["action"]          = actions
    out["confidence"]      = conf_levels
    out["confidence_note"] = conf_reasons

    if target_roas > 0:
        out["roas_gap_vs_target_pct"] = (out.get("d7_roas", 0) - target_roas) / target_roas * 100
    else:
        out["roas_gap_vs_target_pct"] = 0.0
    out["install_gap_to_min"] = out.get("installs", 0) - min_installs

    def _efficiency_note(row: pd.Series) -> str:
        if int(row.get("installs", 0)) < min_installs:
            return "Sample risk"
        if float(row.get("d7_roas", 0.0)) >= upper:
            return "Strong efficiency"
        if float(row.get("d7_roas", 0.0)) < lower:
            return "Efficiency risk"
        return "Near target"

    out["efficiency_note"] = out.apply(_efficiency_note, axis=1)
    return out
