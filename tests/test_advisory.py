import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend.advisor import FixtureAdvisor, AdvisoryStore, validate_advisory, AdvisoryError
from backend.engine import Engine
from backend.market import FixtureMarket


class AdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: 1800000000,
                             market=FixtureMarket(), advisor=FixtureAdvisor())

    def test_advise_returns_structured_assessment(self):
        result = self.engine.advise({"symbol": "BNBUSDT", "horizon": "short", "question": ""})
        self.assertEqual(result["asset"], "BNBUSDT")
        self.assertEqual(result["horizon"], "short")
        self.assertIn("output", result)
        self.assertEqual(result["output"]["recommendation"], "HOLD")
        self.assertTrue(len(result["evidence_ids"]) > 0)

    def test_invalid_asset_or_horizon_is_rejected(self):
        for payload in [
            {"symbol": "SOLUSDT", "horizon": "short"},
            {"symbol": "BNBUSDT", "horizon": "invalid"},
        ]:
            with self.subTest(payload=payload), self.assertRaises(Exception):
                self.engine.advise(payload)

    def test_validation_rejects_missing_fields(self):
        good = {
            "recommendation": "HOLD", "thesis": "x", "supporting_factors": ["ev1"],
            "opposing_factors": [], "risks": [], "news_impact": "x",
            "portfolio_impact": "x", "missing_inputs": [], "invalidation_conditions": [],
        }
        self.assertTrue(validate_advisory(copy.deepcopy(good), ["ev1"]))
        for key in list(good):
            bad = copy.deepcopy(good)
            del bad[key]
            with self.subTest(missing=key), self.assertRaises(AdvisoryError):
                validate_advisory(bad, ["ev1"])


if __name__ == "__main__":
    unittest.main()
