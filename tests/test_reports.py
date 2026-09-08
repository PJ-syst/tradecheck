import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from backend.engine import Engine
from backend.market import FixtureMarket
from backend.reports import ReportService


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.now_ref = [1800000000]
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: self.now_ref[0],
                             market=FixtureMarket())

    def _pass_time(self):
        self.now_ref[0] += 60

    def test_daily_report_captures_trades(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        self._pass_time()
        report = self.engine.generate_report({"report_type": "daily", "period": "current"})
        calc = report["calculations"]
        self.assertIn("2027-01-15", calc["period_label"])
        self.assertEqual(calc["buys"], 1)
        self.assertEqual(calc["sells"], 0)
        self.assertIn("realized_pnl", calc)

    def test_html_report_round_trips_through_store(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        self._pass_time()
        gen = self.engine.generate_report({"report_type": "daily", "period": "current"})
        html = self.engine.get_report(gen["report"]["id"], format="html")
        self.assertIn("<html", html)

    def test_service_aggregation_for_buy_and_sell(self):
        engine = self.engine
        engine.approve(engine.preview("Buy 20 USDT of BNB")["id"])
        qty = engine.state()["holdings"]["BNB"]
        engine.approve(engine.preview({"side": "SELL", "symbol": "BNBUSDT", "quantity": qty})["id"])
        self._pass_time()
        s = ReportService(portfolio_store=engine.portfolio)
        prices = {row["symbol"]: row["price"] for row in FixtureMarket().snapshot()}
        from backend.reports import current_period
        period = current_period("monthly", "Africa/Kampala", engine.clock())
        result = s.generate("paper", "monthly", period, Decimal(engine.state()["balance"]), prices)
        calc = result["calculations"]
        self.assertEqual(calc["buys"] + calc["sells"], 2)


if __name__ == "__main__":
    unittest.main()
