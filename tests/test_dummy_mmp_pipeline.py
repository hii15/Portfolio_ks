import tempfile
import unittest
from pathlib import Path

import pandas as pd

from data_processing.adapters import ADAPTER_REGISTRY
from data_processing.canonical_schema import coerce_canonical_types
from data_processing.metrics_engine import calculate_media_metrics
from dummy_data.generate_dummy_data import write_mmp_dummy_data, get_mmp_raw_bundle, generate_canonical_dummy_data


class DummyMMPPipelineTests(unittest.TestCase):
    def test_generated_raw_files_cover_three_mmps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_mmp_dummy_data(output_dir=tmpdir, seed=7)
            self.assertEqual(set(written.keys()), {"appsflyer", "adjust", "singular"})

            for slug, paths in written.items():
                for p in paths:
                    self.assertTrue(Path(p).exists(), f"missing generated file: {slug} {p}")

    def test_inmemory_bundle_api(self):
        for mmp in ["AppsFlyer", "Adjust", "Singular"]:
            installs_raw, events_raw, cost_raw = get_mmp_raw_bundle(mmp=mmp, seed=5)
            self.assertGreater(len(installs_raw), 0)
            self.assertGreater(len(events_raw), 0)
            self.assertGreater(len(cost_raw), 0)

    def test_dummy_data_has_korean_media_and_two_creatives(self):
        installs, events, cost = generate_canonical_dummy_data(seed=21)

        expected_media = {"Meta", "Google", "Unity", "TikTok", "Naver", "Kakao", "DCInside", "YouTube"}
        self.assertTrue(expected_media.issubset(set(installs["media_source"].unique())))

        creative_counts = installs.groupby("media_source")["creative"].nunique()
        self.assertTrue((creative_counts >= 2).all())

        self.assertGreater(len(installs), 30000)
        self.assertGreater(len(cost), 400)


    def test_dummy_seed_snapshot_is_deterministic(self):
        installs, events, cost = generate_canonical_dummy_data(seed=11)

        self.assertEqual(len(installs), 105497)
        self.assertEqual(len(events), 13481)
        self.assertEqual(len(cost), 480)

        installs_by_media = installs.groupby("media_source")["user_key"].nunique().to_dict()
        self.assertEqual(installs_by_media["Naver"], 13599)
        self.assertEqual(installs_by_media["Meta"], 13058)

        self.assertAlmostEqual(float(cost["spend"].sum()), 494312296.17, places=2)

    def test_dummy_currency_is_krw_scale(self):
        appsflyer_installs, appsflyer_events, appsflyer_cost = get_mmp_raw_bundle(mmp="AppsFlyer", seed=13)
        adjust_installs, adjust_events, adjust_cost = get_mmp_raw_bundle(mmp="Adjust", seed=13)
        singular_installs, singular_events, singular_cost = get_mmp_raw_bundle(mmp="Singular", seed=13)

        self.assertIn("af_revenue_krw", appsflyer_events.columns)
        self.assertIn("revenue_krw", adjust_events.columns)
        self.assertIn("spend_krw", singular_cost.columns)

        self.assertGreater(float(appsflyer_events["af_revenue_krw"].median()), 1000)
        self.assertGreater(float(adjust_events["revenue_krw"].median()), 1000)
        self.assertGreater(float(singular_cost["spend_krw"].median()), 100000)

    def test_raw_to_canonical_and_metrics_runs_for_each_mmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            write_mmp_dummy_data(output_dir=tmpdir, seed=11)

            for mmp in ["AppsFlyer", "Adjust", "Singular"]:
                slug = mmp.lower()
                installs_raw = pd.read_csv(f"{tmpdir}/{slug}/installs_raw.csv")
                events_raw = pd.read_csv(f"{tmpdir}/{slug}/events_raw.csv")
                cost_raw = pd.read_csv(f"{tmpdir}/{slug}/cost_raw.csv")

                adapter = ADAPTER_REGISTRY[mmp]()
                canonical = coerce_canonical_types(
                    adapter.normalize_installs(installs_raw),
                    adapter.normalize_events(events_raw),
                    adapter.normalize_cost(cost_raw),
                )
                metrics = calculate_media_metrics(canonical.installs, canonical.events, canonical.cost)

                self.assertGreater(len(metrics), 0)
                self.assertIn("d7_roas", metrics.columns)

if __name__ == "__main__":
    unittest.main()
