import unittest
import pandas as pd

from data_processing.adapters import AppsFlyerAdapter
from data_processing.canonical_schema import (
    coerce_canonical_types,
    format_validation_issues,
    validate_canonical_bundle,
    validate_canonical_bundle_detailed,
)
from data_processing.metrics_engine import calculate_media_metrics, calculate_cohort_curve
from data_processing.liveops_analysis import compare_liveops_impact, compare_liveops_impact_by_level, derive_liveops_actions
from data_processing.decision_engine import apply_decision_logic


class NewEngineModulesTests(unittest.TestCase):
    def test_appsflyer_adapter_maps_common_time_and_revenue_fields(self):
        installs_raw = pd.DataFrame(
            {
                "appsflyer_id": ["u1"],
                "install_time_utc": ["2026-01-01 10:00:00"],
                "media_source": ["Meta"],
                "campaign": ["C1"],
            }
        )
        events_raw = pd.DataFrame(
            {
                "appsflyer_id": ["u1"],
                "event_time_utc": ["2026-01-02 11:00:00"],
                "event_name": ["af_purchase"],
                "af_revenue_usd": [10.0],
            }
        )

        adapter = AppsFlyerAdapter()
        installs = adapter.normalize_installs(installs_raw)
        events = adapter.normalize_events(events_raw)
        canonical = coerce_canonical_types(installs, events, pd.DataFrame())

        self.assertIn("user_key", canonical.installs.columns)
        self.assertIn("install_time", canonical.installs.columns)
        self.assertIn("event_time", canonical.events.columns)
        self.assertEqual(float(canonical.events.loc[0, "revenue"]), 10.0)

    def test_metrics_only_count_purchase_events(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "install_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "media_source": ["Meta", "Meta"],
                "campaign": ["C1", "C1"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "event_time": pd.to_datetime(["2026-01-02", "2026-01-02"]),
                "event_name": ["session", "af_purchase"],
                "revenue": [999.0, 10.0],
            }
        )
        cost = pd.DataFrame(
            {
                "date": ["2026-01-01"],
                "media_source": ["Meta"],
                "campaign": ["C1"],
                "impressions": [1000],
                "clicks": [100],
                "spend": [20.0],
            }
        )

        metrics = calculate_media_metrics(installs, events, cost)
        self.assertAlmostEqual(float(metrics.loc[0, "d7_revenue"]), 10.0)
        self.assertAlmostEqual(float(metrics.loc[0, "purchase_rate"]), 0.5)

    def test_cohort_curve_keeps_media_without_events(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "install_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "media_source": ["Meta", "Google"],
                "campaign": ["C1", "C1"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1"],
                "event_time": pd.to_datetime(["2026-01-02"]),
                "event_name": ["af_purchase"],
                "revenue": [10.0],
            }
        )

        curve = calculate_cohort_curve(installs, events, max_day=3)
        self.assertIn("Google", set(curve["media_source"]))
        google_ltv = curve[curve["media_source"] == "Google"]["ltv"].sum()
        self.assertAlmostEqual(float(google_ltv), 0.0)

    def test_liveops_impact_uses_purchase_only(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "install_time": pd.to_datetime(["2026-01-10", "2026-01-03"]),
                "media_source": ["Meta", "Meta"],
                "campaign": ["C1", "C1"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "event_time": pd.to_datetime(["2026-01-11", "2026-01-04"]),
                "event_name": ["af_purchase", "session"],
                "revenue": [10.0, 99.0],
            }
        )

        out = compare_liveops_impact(installs, events, "2026-01-10", "2026-01-10", baseline_days=1)
        self.assertAlmostEqual(float(out.loc[0, "liveops_d7_ltv"]), 10.0)
        self.assertAlmostEqual(float(out.loc[0, "baseline_d7_ltv"]), 0.0)


    def test_liveops_by_level_handles_empty_period_without_crash(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "install_time": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "media_source": ["Meta", "Google"],
                "campaign": ["C1", "C1"],
                "adset": ["A1", "A1"],
                "creative": ["CR1", "CR1"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1"],
                "event_time": pd.to_datetime(["2026-01-03"]),
                "event_name": ["af_purchase"],
                "revenue": [1000.0],
            }
        )

        out = compare_liveops_impact_by_level(
            installs,
            events,
            event_start="2026-02-10",
            event_end="2026-02-12",
            baseline_days=3,
            level="campaign",
        )
        self.assertIn("segment", out.columns)
        self.assertTrue(out.empty)


    def test_liveops_supports_campaign_adset_level(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "install_time": pd.to_datetime(["2026-01-10", "2026-01-10", "2026-01-03", "2026-01-03"]),
                "media_source": ["Meta", "Google", "Meta", "Google"],
                "campaign": ["C1", "C1", "C1", "C1"],
                "adset": ["A1", "A1", "A2", "A2"],
                "creative": ["CR1", "CR1", "CR2", "CR2"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "event_time": pd.to_datetime(["2026-01-11", "2026-01-11", "2026-01-04", "2026-01-04"]),
                "event_name": ["af_purchase", "af_purchase", "af_purchase", "af_purchase"],
                "revenue": [10000.0, 8000.0, 5000.0, 3000.0],
            }
        )
        out = compare_liveops_impact_by_level(
            installs,
            events,
            event_start="2026-01-10",
            event_end="2026-01-10",
            baseline_days=1,
            level="campaign_adset",
        )
        self.assertIn("campaign", out.columns)
        self.assertIn("adset", out.columns)
        self.assertNotIn("media_source", out.columns)

    def test_liveops_impact_supports_level_breakdown(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "install_time": pd.to_datetime(["2026-01-10", "2026-01-10", "2026-01-03", "2026-01-03"]),
                "media_source": ["Meta", "Google", "Meta", "Google"],
                "campaign": ["C1", "C1", "C1", "C1"],
                "adset": ["A1", "A1", "A1", "A1"],
                "creative": ["CR1", "CR1", "CR1", "CR1"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "event_time": pd.to_datetime(["2026-01-11", "2026-01-11", "2026-01-04", "2026-01-04"]),
                "event_name": ["af_purchase", "af_purchase", "af_purchase", "af_purchase"],
                "revenue": [10000.0, 8000.0, 5000.0, 3000.0],
            }
        )

        out = compare_liveops_impact_by_level(
            installs,
            events,
            event_start="2026-01-10",
            event_end="2026-01-10",
            baseline_days=1,
            level="media_source",
        )
        self.assertIn("segment", out.columns)
        self.assertIn("impact", out.columns)
        self.assertEqual(set(out["media_source"]), {"Meta", "Google"})


    def test_derive_liveops_actions_labels_operational_priority(self):
        impact_df = pd.DataFrame(
            {
                "segment": ["Meta", "Google", "Unity", "TikTok"],
                "impact": [40.0, -25.0, 5.0, 100.0],
                "baseline_d7_ltv": [100.0, 100.0, 100.0, 100.0],
                "liveops_sample": [300, 280, 250, 20],
                "baseline_sample": [320, 300, 240, 15],
            }
        )

        out = derive_liveops_actions(impact_df, min_sample=100)

        action_map = dict(zip(out["segment"], out["action_label"]))
        self.assertEqual(action_map["Meta"], "증액 후보")
        self.assertEqual(action_map["Google"], "점검/감액 후보")
        self.assertEqual(action_map["Unity"], "관찰 유지")
        self.assertEqual(action_map["TikTok"], "보류(표본 부족)")
        self.assertIn("impact_pct", out.columns)

    def test_metrics_support_creative_level_with_allocated_cost(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "install_time": pd.to_datetime(["2026-01-01"] * 4),
                "media_source": ["Meta"] * 4,
                "campaign": ["C1"] * 4,
                "adset": ["A1", "A1", "A2", "A2"],
                "creative": ["CR1", "CR1", "CR2", "CR2"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u3"],
                "event_time": pd.to_datetime(["2026-01-02", "2026-01-03"]),
                "event_name": ["af_purchase", "af_purchase"],
                "revenue": [10000.0, 15000.0],
            }
        )
        cost = pd.DataFrame(
            {
                "date": ["2026-01-01"],
                "media_source": ["Meta"],
                "campaign": ["C1"],
                "impressions": [1000],
                "clicks": [100],
                "spend": [20000.0],
            }
        )

        out = calculate_media_metrics(installs, events, cost, level="creative")
        self.assertIn("creative", out.columns)
        self.assertAlmostEqual(float(out["spend"].sum()), 20000.0)


    def test_metrics_support_campaign_adset_level(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2", "u3", "u4"],
                "install_time": pd.to_datetime(["2026-01-01"] * 4),
                "media_source": ["Meta", "Google", "Meta", "Google"],
                "campaign": ["C1", "C1", "C2", "C2"],
                "adset": ["A1", "A1", "A2", "A2"],
                "creative": ["CR1", "CR1", "CR2", "CR2"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1", "u3"],
                "event_time": pd.to_datetime(["2026-01-02", "2026-01-03"]),
                "event_name": ["af_purchase", "af_purchase"],
                "revenue": [10000.0, 15000.0],
            }
        )
        cost = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-01"],
                "media_source": ["Meta", "Google"],
                "campaign": ["C1", "C2"],
                "impressions": [1000, 1000],
                "clicks": [100, 100],
                "spend": [20000.0, 22000.0],
            }
        )

        out = calculate_media_metrics(installs, events, cost, level="campaign_adset")
        self.assertIn("campaign", out.columns)
        self.assertIn("adset", out.columns)
        self.assertNotIn("media_source", out.columns)

    def test_cohort_curve_supports_creative_level(self):
        installs = pd.DataFrame(
            {
                "user_key": ["u1", "u2"],
                "install_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "media_source": ["Meta", "Meta"],
                "campaign": ["C1", "C1"],
                "adset": ["A1", "A2"],
                "creative": ["CR1", "CR2"],
            }
        )
        events = pd.DataFrame(
            {
                "user_key": ["u1"],
                "event_time": pd.to_datetime(["2026-01-02"]),
                "event_name": ["af_purchase"],
                "revenue": [1000.0],
            }
        )

        curve = calculate_cohort_curve(installs, events, max_day=3, level="creative")
        self.assertIn("segment", curve.columns)
        self.assertTrue(curve["segment"].str.contains("CR1").any())

    def test_decision_engine_emits_reason(self):
        base = pd.DataFrame(
            {
                "media_source": ["Meta", "Google"],
                "campaign": ["C1", "C2"],
                "installs": [100, 300],
                "d7_roas": [0.8, 1.25],
            }
        )
        out = apply_decision_logic(base, target_roas=1.0, min_installs=200)
        self.assertIn("decision_reason", out.columns)
        self.assertIn("efficiency_note", out.columns)
        self.assertIn("roas_gap_vs_target_pct", out.columns)
        self.assertIn("install_gap_to_min", out.columns)
        self.assertEqual(out.loc[0, "decision"], "Hold (Low Sample)")
        self.assertEqual(out.loc[1, "decision"], "Scale Up")
        self.assertLess(float(out.loc[0, "install_gap_to_min"]), 0)


    def test_validate_canonical_bundle_returns_user_friendly_messages(self):
        installs = pd.DataFrame({"user_key": ["u1"], "install_time": [pd.NaT], "media_source": [pd.NA], "campaign": [pd.NA]})
        events = pd.DataFrame({"user_key": ["u1"], "event_time": [pd.NaT], "event_name": [pd.NA], "revenue": [0.0]})
        canonical = coerce_canonical_types(installs, events, pd.DataFrame())

        issues = validate_canonical_bundle(canonical)
        self.assertGreaterEqual(len(issues), 3)
        self.assertTrue(any("[E002]" in msg for msg in issues))
        self.assertTrue(any("[E003]" in msg for msg in issues))
        self.assertTrue(any("[E006]" in msg for msg in issues))

    def test_validation_detail_and_formatter_include_fix_guide(self):
        installs = pd.DataFrame({"user_key": ["u1"], "install_time": [pd.NaT], "media_source": [pd.NA], "campaign": [pd.NA]})
        events = pd.DataFrame({"user_key": ["u1"], "event_time": [pd.NaT], "event_name": [pd.NA], "revenue": [0.0]})
        canonical = coerce_canonical_types(installs, events, pd.DataFrame())

        detailed = validate_canonical_bundle_detailed(canonical)
        rendered = format_validation_issues(detailed)

        self.assertTrue(any(item["code"] == "E002" for item in detailed))
        self.assertIn("해결:", rendered)
        self.assertIn("[E002]", rendered)


if __name__ == "__main__":
    unittest.main()
