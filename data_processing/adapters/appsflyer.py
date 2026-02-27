from __future__ import annotations

import pandas as pd

from .base import BaseMMPAdapter


class AppsFlyerAdapter(BaseMMPAdapter):
    def normalize_installs(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(
            columns={
                "appsflyer_id": "user_key",
                "advertising_id": "user_key",
                "install_datetime": "install_time",
                "install_time_utc": "install_time",
                "country_code": "geo",
            }
        ).copy()

    def normalize_events(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "af_revenue_krw" in out.columns:
            out = out.rename(columns={"af_revenue_krw": "revenue"})
        elif "af_revenue_usd" in out.columns:
            out = out.rename(columns={"af_revenue_usd": "revenue"})

        return out.rename(
            columns={
                "appsflyer_id": "user_key",
                "advertising_id": "user_key",
                "event_datetime": "event_time",
                "event_time_utc": "event_time",
                "event_revenue": "revenue",
            }
        ).copy()

    def normalize_cost(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(columns={"cost": "spend", "campaign_name": "campaign"}).copy()
