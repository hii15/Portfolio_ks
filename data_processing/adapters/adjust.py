from __future__ import annotations

import pandas as pd

from .base import BaseMMPAdapter


class AdjustAdapter(BaseMMPAdapter):
    def normalize_installs(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(
            columns={
                "adid": "user_key",
                "installed_at": "install_time",
                "network": "media_source",
                "adgroup": "adset",
                "country": "geo",
                "os_name": "platform",
            }
        ).copy()

    def normalize_events(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "revenue_krw" in out.columns:
            out = out.rename(columns={"revenue_krw": "revenue"})
            out["revenue_currency"] = "KRW"
        elif "revenue_usd" in out.columns:
            out = out.rename(columns={"revenue_usd": "revenue"})
            out["revenue_currency"] = "USD"

        return out.rename(
            columns={
                "adid": "user_key",
                "created_at": "event_time",
                "name": "event_name",
            }
        ).copy()

    def normalize_cost(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.rename(columns={"network": "media_source", "adgroup": "campaign", "cost": "spend"}).copy()
        if "cost_krw" in df.columns:
            out["spend_currency"] = "KRW"
        elif "cost_usd" in df.columns:
            out["spend_currency"] = "USD"
        return out
