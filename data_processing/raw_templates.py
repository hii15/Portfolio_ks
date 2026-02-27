from __future__ import annotations

import pandas as pd

_TEMPLATE_COLUMNS: dict[str, dict[str, list[str]]] = {
    "AppsFlyer": {
        "installs": [
            "appsflyer_id",
            "install_time_utc",
            "media_source",
            "campaign",
            "adset",
            "creative",
            "country_code",
            "platform",
        ],
        "events": ["appsflyer_id", "event_time_utc", "event_name", "af_revenue_krw"],
        "cost": ["date", "media_source", "campaign_name", "impressions", "clicks", "cost"],
    },
    "Adjust": {
        "installs": ["adid", "installed_at", "network", "campaign", "adgroup", "creative", "country", "os_name"],
        "events": ["adid", "created_at", "name", "revenue_krw"],
        "cost": ["date", "network", "adgroup", "impressions", "clicks", "cost"],
    },
    "Singular": {
        "installs": [
            "device_id",
            "install_time_utc",
            "source",
            "campaign",
            "ad_group",
            "creative_name",
            "country_iso",
            "platform_name",
        ],
        "events": ["device_id", "event_time_utc", "event", "revenue_amount"],
        "cost": ["date", "source", "ad_group", "impressions", "clicks", "spend_krw"],
    },
}


def list_template_mmps() -> list[str]:
    return sorted(_TEMPLATE_COLUMNS.keys())


def get_raw_template_bundle(mmp: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if mmp not in _TEMPLATE_COLUMNS:
        raise ValueError(f"Unsupported MMP template: {mmp}")
    spec = _TEMPLATE_COLUMNS[mmp]
    return (
        pd.DataFrame(columns=spec["installs"]),
        pd.DataFrame(columns=spec["events"]),
        pd.DataFrame(columns=spec["cost"]),
    )
