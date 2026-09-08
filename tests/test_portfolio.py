import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from backend.portfolio import PortfolioStore, AccountingError


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "portfolio.sqlite3"
        self.clock_now = [1_800_000_000.0]
        self.store = PortfolioStore(lambda: sqlite3.connect(self.db_path, timeout=10), clock=lambda: self.clock_now[0])

    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def test_default_paper_portfolio_is_created(self):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM portfolios WHERE id='paper'").fetchone()
            self.assertEqual(row["source_type"], "paper")

    def test_buy_and_holdings(self):
        with self.connection() as conn:
            self.store.record_trade(
                conn, portfolio_id="paper", side="BUY", symbol="BNBUSDT",
                quantity=Decimal("0.1"), price=Decimal("600"),
                purchase_cost=Decimal("60"), fee=Decimal("0.06"), net_quote=Decimal("60.06"),
                day="2026-09-08", timestamp=self.clock_now[0], source_id="p1",
            )
        state = self.store.holdings("paper")
        self.assertEqual(state["quantities"]["BNB"], Decimal("0.1"))
        self.assertEqual(state["basis"]["BNB"], Decimal("60.06"))

    def test_buy_then_sell_updates_realized_pnl(self):
        with self.connection() as conn:
            self.store.record_trade(
                conn, portfolio_id="paper", side="BUY", symbol="BNBUSDT",
                quantity=Decimal("1"), price=Decimal("600"),
                purchase_cost=Decimal("600"), fee=Decimal("0.6"), net_quote=Decimal("600.6"),
                day="2026-09-08", timestamp=self.clock_now[0], source_id="p1",
            )
            self.clock_now[0] += 60
            self.store.record_trade(
                conn, portfolio_id="paper", side="SELL", symbol="BNBUSDT",
                quantity=Decimal("0.5"), price=Decimal("700"),
                purchase_cost=Decimal("350"), fee=Decimal("0.35"), net_quote=Decimal("349.65"),
                day="2026-09-08", timestamp=self.clock_now[0], source_id="p2",
            )
        state = self.store.holdings("paper")
        self.assertEqual(state["quantities"]["BNB"], Decimal("0.5"))
        self.assertAlmostEqual(state["realized_pnl"], Decimal("49.35"), places=2)

    def test_holdings_at_timestamp_excludes_later_trades(self):
        with self.connection() as conn:
            self.store.record_trade(
                conn, portfolio_id="paper", side="BUY", symbol="BTCUSDT",
                quantity=Decimal("0.001"), price=Decimal("100000"),
                purchase_cost=Decimal("100"), fee=Decimal("0.1"), net_quote=Decimal("100.1"),
                day="2026-09-08", timestamp=100.0, source_id="p1",
            )
            self.store.record_trade(
                conn, portfolio_id="paper", side="BUY", symbol="BTCUSDT",
                quantity=Decimal("0.001"), price=Decimal("100000"),
                purchase_cost=Decimal("100"), fee=Decimal("0.1"), net_quote=Decimal("100.1"),
                day="2026-09-08", timestamp=200.0, source_id="p2",
            )
        state = self.store.holdings_at("paper", 150.0)
        self.assertEqual(state["quantities"].get("BTC", Decimal("0")), Decimal("0.001"))

    def test_cash_at_reconstructs_from_current_cash(self):
        with self.connection() as conn:
            self.store.record_trade(
                conn, portfolio_id="paper", side="BUY", symbol="BNBUSDT",
                quantity=Decimal("1"), price=Decimal("600"),
                purchase_cost=Decimal("600"), fee=Decimal("0.6"), net_quote=Decimal("600.6"),
                day="2026-09-08", timestamp=100.0, source_id="p1",
            )
        # Current cash 24.4 means initial was 625.0
        cash_then = self.store.cash_at("paper", 150.0, Decimal("24.4"))
        self.assertEqual(cash_then, Decimal("24.4"))


if __name__ == "__main__":
    unittest.main()
