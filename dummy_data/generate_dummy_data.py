from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# 매체별 "현실적 범위(range)" 정의
#
# 설계 원칙:
#   - 각 매체의 특성 방향성은 실무 경험 기반으로 유지
#     (예: YouTube는 CPI 높고 ARPPU 높은 경향, Unity는 CPI 낮고 구매율 낮은 경향)
#   - 그러나 범위가 겹치도록 설계 → 시드에 따라 Unity가 Google을 이기는 경우도 발생
#   - 이것이 실무 현실 (특정 시즌·소재·타겟에 따라 순위가 뒤집힘)
#
# 각 범위의 의미:
#   cpi_range        : 설치당 비용(원) 변동 범위
#   purchase_rate_range : D7 이내 구매 전환율 변동 범위
#   arppu_range      : 구매자 1인당 평균 매출(원) 변동 범위
#   daily_install_range : 일별 캠페인당 설치수 변동 범위
#   daily_volatility : 일별 성과 변동성 계수 (높을수록 날마다 편차가 큼)
# ─────────────────────────────────────────────────────────────────────────────
MEDIA_PROFILES = {
    "Meta": {
        "cpi_range":           (3800, 6200),
        "purchase_rate_range": (0.08, 0.18),
        "arppu_range":         (18000, 31000),
        "daily_install_range": (140, 300),
        "daily_volatility":    0.18,   # 중간 변동성
        "campaigns":           2,
    },
    "Google": {
        "cpi_range":           (4200, 7500),
        "purchase_rate_range": (0.10, 0.22),
        "arppu_range":         (20000, 36000),
        "daily_install_range": (120, 280),
        "daily_volatility":    0.15,   # 상대적으로 안정적
        "campaigns":           2,
    },
    "Unity": {
        "cpi_range":           (2500, 5000),   # 낮은 편이지만 가끔 올라감
        "purchase_rate_range": (0.04, 0.14),   # Google 범위와 일부 겹침 → 이변 가능
        "arppu_range":         (13000, 25000),
        "daily_install_range": (180, 350),     # 물량은 많은 편
        "daily_volatility":    0.28,   # 리워드 특성상 변동성 높음
        "campaigns":           2,
    },
    "TikTok": {
        "cpi_range":           (2800, 5500),
        "purchase_rate_range": (0.06, 0.16),
        "arppu_range":         (15000, 27000),
        "daily_install_range": (160, 320),
        "daily_volatility":    0.25,   # 트렌드 민감 → 변동성 높음
        "campaigns":           2,
    },
    "Naver": {
        "cpi_range":           (4000, 6800),
        "purchase_rate_range": (0.09, 0.19),
        "arppu_range":         (19000, 33000),
        "daily_install_range": (100, 240),
        "daily_volatility":    0.16,
        "campaigns":           2,
    },
    "Kakao": {
        "cpi_range":           (3500, 6000),
        "purchase_rate_range": (0.08, 0.18),
        "arppu_range":         (18000, 30000),
        "daily_install_range": (110, 250),
        "daily_volatility":    0.17,
        "campaigns":           2,
    },
    "DCInside": {
        "cpi_range":           (2200, 4500),   # 저단가 커뮤니티 매체
        "purchase_rate_range": (0.04, 0.12),
        "arppu_range":         (12000, 22000),
        "daily_install_range": (80, 200),
        "daily_volatility":    0.32,   # 커뮤니티 반응 매우 불규칙
        "campaigns":           2,
    },
    "YouTube": {
        "cpi_range":           (5000, 8500),   # 높은 편이지만 범위가 넓음
        "purchase_rate_range": (0.11, 0.23),
        "arppu_range":         (22000, 38000),
        "daily_install_range": (90, 220),
        "daily_volatility":    0.14,   # 브랜드 광고 특성상 비교적 안정적
        "campaigns":           2,
    },
}

# 소재(Creative) 범위: 고정값 → 범위 기반으로 변경
# CR1이 물량 주도, CR2가 효율 주도인 경향은 유지하되 차이가 고정되지 않음
CREATIVE_BASE = [
    {
        "suffix": "CR1",
        "install_share_range": (0.45, 0.65),   # 물량 주도 소재 (더 넓은 범위)
        "purchase_mult_range": (0.85, 1.10),
        "arppu_mult_range":    (0.90, 1.05),
    },
    {
        "suffix": "CR2",
        "install_share_range": (0.35, 0.55),   # 효율 주도 소재
        "purchase_mult_range": (0.95, 1.20),   # 가끔 CR1보다 효율이 낮을 수도 있음
        "arppu_mult_range":    (0.95, 1.15),
    },
]


def _sample_media_profiles(rng: np.random.Generator) -> dict:
    """
    시드 기반으로 매체별 실제 성과 파라미터를 범위 내에서 샘플링.
    같은 시드 = 같은 결과 (재현성 보장), 다른 시드 = 다른 순위 구도.
    """
    profiles = {}
    for media, spec in MEDIA_PROFILES.items():
        profiles[media] = {
            "cpi":           rng.uniform(*spec["cpi_range"]),
            "purchase_rate": rng.uniform(*spec["purchase_rate_range"]),
            "arppu":         rng.uniform(*spec["arppu_range"]),
            "daily_install_range": spec["daily_install_range"],
            "daily_volatility":    spec["daily_volatility"],
            "campaigns":     spec["campaigns"],
        }
    return profiles


def _sample_creative_profiles(rng: np.random.Generator) -> list:
    """소재 성과 배율도 범위 내에서 샘플링."""
    creatives = []
    for base in CREATIVE_BASE:
        share = rng.uniform(*base["install_share_range"])
        creatives.append({
            "suffix":        base["suffix"],
            "install_share": share,
            "purchase_mult": rng.uniform(*base["purchase_mult_range"]),
            "arppu_mult":    rng.uniform(*base["arppu_mult_range"]),
        })
    # install_share 합이 1이 되도록 정규화
    total = sum(c["install_share"] for c in creatives)
    for c in creatives:
        c["install_share"] /= total
    return creatives


def generate_canonical_dummy_data(seed: int = 42):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01")
    days = 30

    # ── 매체/소재 성과 파라미터를 시드 기반으로 샘플링 ──
    sampled_profiles = _sample_media_profiles(rng)
    creative_profiles = _sample_creative_profiles(rng)
    creative_probs = [c["install_share"] for c in creative_profiles]

    # LiveOps 부스트도 고정 1.3이 아니라 범위 내 샘플링
    # → 시나리오마다 이벤트 효과 강도가 다름
    liveops_boost_value = rng.uniform(1.15, 1.55)

    installs_rows, events_rows, cost_rows = [], [], []
    uid = 1

    for day_offset in range(days):
        day = start + pd.Timedelta(days=day_offset)
        liveops_boost = (
            liveops_boost_value
            if pd.Timestamp("2026-01-15") <= day <= pd.Timestamp("2026-01-21")
            else 1.0
        )

        for media, profile in sampled_profiles.items():
            # ── 일별 성과 변동성 적용 ──
            # daily_shock: 매체마다 매일 성과가 흔들리는 정도 (실무의 경쟁 환경·입찰 변동 반영)
            volatility = profile["daily_volatility"]
            daily_shock = float(rng.normal(loc=1.0, scale=volatility))
            daily_shock = max(0.4, min(daily_shock, 2.0))  # 극단값 클리핑

            for campaign_idx in range(1, profile["campaigns"] + 1):
                campaign_name = f"{media}_C{campaign_idx}"

                # 캠페인별 성과 배율도 범위 기반 (고정 +3%가 아님)
                campaign_mult = rng.uniform(0.90, 1.15)

                lo, hi = profile["daily_install_range"]
                daily_installs = int(rng.integers(lo, hi))

                creative_installs = rng.multinomial(daily_installs, creative_probs)
                campaign_user_keys = []

                for creative_cfg, installs_n in zip(creative_profiles, creative_installs):
                    creative_name = f"{media}_{creative_cfg['suffix']}"
                    adset_name = f"{media}_A{campaign_idx}_{creative_cfg['suffix']}"
                    creative_user_keys = []

                    for _ in range(int(installs_n)):
                        user_key = f"u{uid}"
                        uid += 1
                        campaign_user_keys.append(user_key)
                        creative_user_keys.append(user_key)
                        installs_rows.append({
                            "user_key":    user_key,
                            "install_time": day + pd.Timedelta(hours=int(rng.integers(0, 24))),
                            "media_source": media,
                            "campaign":    campaign_name,
                            "adset":       adset_name,
                            "creative":    creative_name,
                            "geo":         rng.choice(["KR", "JP", "US"], p=[0.70, 0.20, 0.10]),
                            "platform":    "iOS" if uid % 2 == 0 else "Android",
                        })

                    # 구매 전환율 = 기본 × LiveOps부스트 × daily_shock × 소재배율
                    purchase_rate = (
                        profile["purchase_rate"]
                        * liveops_boost
                        * daily_shock
                        * creative_cfg["purchase_mult"]
                    )
                    purchase_rate = max(0.01, min(purchase_rate, 0.60))  # 클리핑
                    purchases = int(installs_n * purchase_rate)

                    if purchases > 0 and creative_user_keys:
                        buyers = rng.choice(
                            creative_user_keys,
                            size=min(purchases, len(creative_user_keys)),
                            replace=False,
                        )
                        revenue_total = (
                            len(buyers)
                            * profile["arppu"]
                            * creative_cfg["arppu_mult"]
                            * campaign_mult
                            * daily_shock          # ARPPU도 daily_shock 영향 받음
                            * rng.uniform(0.85, 1.15)
                        )
                        rev_per_purchase = revenue_total / len(buyers)

                        for buyer in buyers:
                            # 현실적인 구매 시점 분포:
                            # - D1~D3 집중 (첫 인상이 강한 시기)
                            # - D7~D14 2차 구매 (게임 진입 후 과금 결정)
                            # - D15~D30 장기 잔존 과금
                            # geometric 분포로 초반 집중 + 롱테일 구조 구현
                            lag_base = int(rng.geometric(p=0.18)) - 1  # 평균 약 4.6일
                            lag = min(lag_base, 29)  # 최대 29일 (D30까지 반영)
                            events_rows.append({
                                "user_key":   buyer,
                                "event_time": day + pd.Timedelta(days=lag, hours=int(rng.integers(0, 24))),
                                "event_name": "af_purchase",
                                "revenue":    round(float(rev_per_purchase * rng.uniform(0.75, 1.25)), 2),
                            })

                if campaign_user_keys:
                    cost_rows.append({
                        "date":        day.date(),
                        "media_source": media,
                        "campaign":    campaign_name,
                        "impressions": int(len(campaign_user_keys) * rng.integers(22, 50)),
                        "clicks":      int(len(campaign_user_keys) * rng.integers(3, 9)),
                        # CPI도 daily_shock 반영 (입찰가 변동)
                        "spend": round(
                            len(campaign_user_keys)
                            * profile["cpi"]
                            * campaign_mult
                            * float(rng.normal(loc=1.0, scale=0.08))  # 비용은 작은 변동성
                            , 2
                        ),
                    })

    return pd.DataFrame(installs_rows), pd.DataFrame(events_rows), pd.DataFrame(cost_rows)


# ─────────────────────────────────────────────────────────────────────────────
# 이하 MMP Raw 변환 함수 및 유틸 - 기존과 동일
# ─────────────────────────────────────────────────────────────────────────────

def to_appsflyer_raw(installs: pd.DataFrame, events: pd.DataFrame, cost: pd.DataFrame):
    installs_raw = installs.rename(columns={
        "user_key":    "appsflyer_id",
        "install_time": "install_time_utc",
        "geo":         "country_code",
    })
    events_raw = events.rename(columns={
        "user_key":   "appsflyer_id",
        "event_time": "event_time_utc",
        "revenue":    "af_revenue_krw",
    })
    cost_raw = cost.rename(columns={"spend": "cost", "campaign": "campaign_name"})
    return installs_raw, events_raw, cost_raw


def to_adjust_raw(installs: pd.DataFrame, events: pd.DataFrame, cost: pd.DataFrame):
    installs_raw = installs.rename(columns={
        "user_key":    "adid",
        "install_time": "installed_at",
        "media_source": "network",
        "adset":       "adgroup",
        "geo":         "country",
        "platform":    "os_name",
    })
    events_raw = events.rename(columns={
        "user_key":   "adid",
        "event_time": "created_at",
        "event_name": "name",
        "revenue":    "revenue_krw",
    })
    cost_raw = cost.rename(columns={"media_source": "network", "campaign": "adgroup", "spend": "cost"})
    return installs_raw, events_raw, cost_raw


def to_singular_raw(installs: pd.DataFrame, events: pd.DataFrame, cost: pd.DataFrame):
    installs_raw = installs.rename(columns={
        "user_key":    "device_id",
        "install_time": "install_time_utc",
        "media_source": "source",
        "adset":       "ad_group",
        "creative":    "creative_name",
        "geo":         "country_iso",
        "platform":    "platform_name",
    })
    events_raw = events.rename(columns={
        "user_key":   "device_id",
        "event_time": "event_time_utc",
        "event_name": "event",
        "revenue":    "revenue_amount",
    })
    cost_raw = cost.rename(columns={"media_source": "source", "campaign": "ad_group", "spend": "spend_krw"})
    return installs_raw, events_raw, cost_raw


MMP_CONVERTERS = {
    "AppsFlyer": to_appsflyer_raw,
    "Adjust":    to_adjust_raw,
    "Singular":  to_singular_raw,
}


def get_mmp_raw_bundle(mmp: str, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if mmp not in MMP_CONVERTERS:
        raise ValueError(f"Unsupported MMP: {mmp}")
    installs, events, cost = generate_canonical_dummy_data(seed=seed)
    return MMP_CONVERTERS[mmp](installs, events, cost)


def write_mmp_dummy_data(output_dir: str = "dummy_data", seed: int = 42) -> dict[str, tuple[str, str, str]]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    installs, events, cost = generate_canonical_dummy_data(seed=seed)

    written = {}
    for mmp, converter in MMP_CONVERTERS.items():
        slug = mmp.lower()
        mmp_dir = base / slug
        mmp_dir.mkdir(parents=True, exist_ok=True)

        i_raw, e_raw, c_raw = converter(installs, events, cost)

        i_path = mmp_dir / "installs_raw.csv"
        e_path = mmp_dir / "events_raw.csv"
        c_path = mmp_dir / "cost_raw.csv"

        i_raw.to_csv(i_path, index=False)
        e_raw.to_csv(e_path, index=False)
        c_raw.to_csv(c_path, index=False)
        written[slug] = (str(i_path), str(e_path), str(c_path))

    return written


if __name__ == "__main__":
    outputs = write_mmp_dummy_data(output_dir="dummy_data", seed=42)
    for mmp, paths in outputs.items():
        print(f"[{mmp}] installs={paths[0]} events={paths[1]} cost={paths[2]}")
