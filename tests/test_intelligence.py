import unittest

import pandas as pd

from scamtrace.geo import distance_km, geo_indicators, synthetic_geo_fixture
from scamtrace.ml import _evaluation_splits
from scamtrace.network import analyze_signals, trace_network


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.signals = [
            {
                "id": "s1",
                "from_institution_id": "northstar",
                "from_account_ref": "a",
                "to_institution_id": "harbor",
                "to_account_ref": "b",
                "amount": "25000",
                "occurred_at": "2026-01-01T10:00:00+00:00",
            },
            {
                "id": "s2",
                "from_institution_id": "harbor",
                "from_account_ref": "b",
                "to_institution_id": "cedar",
                "to_account_ref": "c",
                "amount": "24000",
                "occurred_at": "2026-01-01T10:05:00+00:00",
            },
        ]

    def test_graph_indicators_include_rapid_pass_through(self):
        result = analyze_signals(self.signals)
        account = result["metrics"]["harbor:b"]
        self.assertEqual(account["risk_indicator"], 85)
        self.assertIn("Funds forwarded within 10 minutes", account["reasons"])
        self.assertIn("Connected activity spans three institutions", account["reasons"])
        self.assertEqual(account["in_degree"], 1)
        self.assertEqual(account["out_degree"], 1)

    def test_trace_is_bounded_and_directional_edges_are_preserved(self):
        result = trace_network(self.signals, "northstar:a", max_depth=1)
        self.assertEqual({node["id"] for node in result["nodes"]}, {"northstar:a", "harbor:b"})
        self.assertEqual(result["edges"][0]["signal_id"], "s1")


class GeographyTests(unittest.TestCase):
    def test_distance_is_symmetric_and_rejects_invalid_coordinates(self):
        forward = distance_km((10, 10), (35, 45))
        backward = distance_km((35, 45), (10, 10))
        self.assertAlmostEqual(forward, backward)
        with self.assertRaises(ValueError):
            distance_km((91, 0), (0, 0))

    def test_fixture_is_separate_and_provenance_labelled(self):
        fixture = synthetic_geo_fixture()
        self.assertTrue(all(item["synthetic"] for item in fixture))
        indicators = geo_indicators(fixture)
        self.assertEqual(len(indicators), 1)
        self.assertTrue(indicators[0]["synthetic"])
        self.assertGreater(indicators[0]["distance_km"], 1000)


class ModelSplitTests(unittest.TestCase):
    def test_dataset_without_time_uses_stratified_three_way_split(self):
        frame = pd.DataFrame({"V1": range(100), "Amount": range(100)})
        labels = pd.Series([0] * 90 + [1] * 10)
        splits = _evaluation_splits(frame, labels)
        self.assertIn("no Time column", splits[-1])
        self.assertEqual([len(part) for part in splits[:3]], [70, 15, 15])
        self.assertTrue(all(part.nunique() == 2 for part in splits[3:6]))


if __name__ == "__main__":
    unittest.main()
