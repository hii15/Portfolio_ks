from __future__ import annotations

import pandas as pd

from .base import BaseMMPAdapter


class SingularAdapter(BaseMMPAdapter):
    def normalize_installs(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.rename(
            columns={
                "device_id": "user_key",
                "install_time_utc": "install_time",
                "source": "media_source",
                "ad_group": "adset",
                "creative_name": "creative",
                "country_iso": "geo",
                "platform_name": "platform",
            }
        ).copy()
        if "revenue_krw" in df.columns:
            out["revenue_currency"] = "KRW"
        elif "revenue_usd" in df.columns:
            out["revenue_currency"] = "USD"
        return out

    def normalize_events(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.rename(
            columns={
                "device_id": "user_key",
                "event_time_utc": "event_time",
                "event": "event_name",
                "revenue_amount": "revenue",
            }
        ).copy()

    def normalize_cost(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "spend_krw" in out.columns:
            out = out.rename(columns={"spend_krw": "spend"})
            out["spend_currency"] = "KRW"
        elif "spend_usd" in out.columns:
            out = out.rename(columns={"spend_usd": "spend"})
            out["spend_currency"] = "USD"

        return out.rename(columns={"source": "media_source", "ad_group": "campaign"}).copy()
