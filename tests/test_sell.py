import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from backend.engine import Engine, InvalidRequest
from backend.market import FixtureMarket


class SellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: self.now, market=FixtureMarket())

    def test_sell_preview_rejects_missing_holdings(self):
        result = self.engine.preview({"side": "SELL", "symbol": "BNBUSDT", "quantity": "0.01"})
        self.assertFalse(result["allowed"])
        self.assertIn("Available holdings", str(result["checks"]))

    def test_buy_then_sell_reduces_holdings_and_credits_cash(self):
        buy = self.engine.preview("Buy 20 USDT of BNB")
        self.engine.approve(buy["id"])
        # Now own some BNB
        holdings = self.engine.state()["holdings"]
        qty = holdings.get("BNB", "0")
        sell = self.engine.preview({"side": "SELL", "symbol": "BNBUSDT", "quantity": qty})
        self.assertTrue(sell["allowed"])
        self.assertEqual(sell["side"], "SELL")
        self.engine.approve(sell["id"])
        state = self.engine.state()
        self.assertEqual(state["holdings"].get("BNB", "0"), "0")
        # Cash roughly restored minus fees
        self.assertGreater(Decimal(state["balance"]), Decimal("124.50"))

    def test_sell_does_not_affect_daily_buy_budget(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        qty = self.engine.state()["holdings"]["BNB"]
        self.engine.approve(self.engine.preview({"side": "SELL", "symbol": "BNBUSDT", "quantity": qty})["id"])
        self.assertEqual(self.engine.state()["spent_today"], "20.02")


if __name__ == "__main__":
    unittest.main()
