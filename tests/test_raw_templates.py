import unittest

from data_processing.raw_templates import get_raw_template_bundle, list_template_mmps


class RawTemplateTests(unittest.TestCase):
    def test_supported_mmps_have_required_templates(self):
        mmps = list_template_mmps()
        self.assertEqual(set(mmps), {"Adjust", "AppsFlyer", "Singular"})

        for mmp in mmps:
            installs, events, cost = get_raw_template_bundle(mmp)
            self.assertEqual(len(installs), 0)
            self.assertEqual(len(events), 0)
            self.assertEqual(len(cost), 0)
            self.assertGreaterEqual(len(installs.columns), 6)
            self.assertGreaterEqual(len(events.columns), 4)
            self.assertGreaterEqual(len(cost.columns), 6)

    def test_invalid_mmp_raises(self):
        with self.assertRaises(ValueError):
            get_raw_template_bundle("Unknown")


if __name__ == "__main__":
    unittest.main()
