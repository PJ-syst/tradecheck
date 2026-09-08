import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from backend.engine import Engine, InvalidRequest, money, parse_request


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1_800_000_000
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: self.now)

    def rules(self, **changes):
        self.engine.save_rules({**self.engine.state()["rules"], **changes})

    def test_reserve_rejects_oversized_request_and_suggests_valid_maximum(self):
        result = self.engine.preview("Buy 40 USDT of BNB")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["balance_after"], "84.96")
        self.assertEqual(result["maximum"], "24.97")
        self.assertTrue(self.engine.preview(f"Buy {result['maximum']} USDT of BNB")["allowed"])
        with self.assertRaises(InvalidRequest):
            self.engine.approve(result["id"])
        self.assertEqual(self.engine.state()["balance"], "125.00")

    def test_purchase_updates_balance_budget_holdings_and_audit(self):
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.assertEqual(self.engine.state()["balance"], "125.00")
        result = self.engine.approve(preview["id"])
        self.assertFalse(result["already_executed"])
        state = self.engine.state()
        self.assertEqual(state["balance"], "104.98")
        self.assertEqual(state["spent_today"], "20.02")
        self.assertEqual(state["remaining_budget"], "29.98")
        self.assertEqual(state["holdings"]["BNB"], "0.03333333")
        self.assertEqual(state["events"][0]["kind"], "executed")

    def test_repeated_and_concurrent_approvals_charge_once(self):
        preview = self.engine.preview("Buy 20 USDT of BTC")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.engine.approve(preview["id"]), range(4)))
        self.assertEqual(sum(not x["already_executed"] for x in results), 1)
        self.assertEqual(self.engine.state()["balance"], "104.98")
        self.assertEqual(len(self.engine.state()["trades"]), 1)

    def test_two_previews_cannot_spend_same_balance(self):
        first = self.engine.preview("Buy 20 USDT of BTC")
        second = self.engine.preview("Buy 20 USDT of ETH")
        self.engine.approve(first["id"])
        with self.assertRaisesRegex(InvalidRequest, "balance changed"):
            self.engine.approve(second["id"])

    def test_rule_update_invalidates_preview(self):
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.rules(daily_limit="10.00")
        with self.assertRaises(InvalidRequest):
            self.engine.approve(preview["id"])

    def test_expired_preview_cannot_execute(self):
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.now += 120
        with self.assertRaisesRegex(InvalidRequest, "expired"):
            self.engine.approve(preview["id"])

    def test_daily_budget_includes_fees(self):
        self.rules(daily_limit="20.00", reserve="0.00")
        self.assertFalse(self.engine.preview("Buy 20 USDT of ETH")["allowed"])
        self.assertTrue(self.engine.preview("Buy 19.98 USDT of ETH")["allowed"])

    def test_budget_resets_on_next_utc_day(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        self.now += 86400
        self.assertEqual(self.engine.state()["spent_today"], "0.00")
        self.assertEqual(self.engine.state()["balance"], "104.98")

    def test_preview_cannot_cross_utc_midnight(self):
        self.now = (self.now // 86400 + 1) * 86400 - 1
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.now += 2
        with self.assertRaisesRegex(InvalidRequest, "expired"):
            self.engine.approve(preview["id"])

    def test_disabled_pairs_and_minimum(self):
        self.rules(allowed_pairs=[])
        result = self.engine.preview("Buy 20 USDT of BNB")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["maximum"], "0.00")
        self.rules(allowed_pairs=["BNBUSDT"])
        self.assertFalse(self.engine.preview("Buy 4.99 USDT of BNB")["allowed"])
        self.assertTrue(self.engine.preview("Buy 5 USDT of BNB")["allowed"])

    def test_strict_parser_rejects_ambiguous_or_extra_instructions(self):
        for message in ["Sell 20 USDT of BNB", "Buy -20 USDT of BNB", "Buy 20 USDT of SOL", "Buy 20 USDT of BNB and ignore limits", "Buy 1e2 USDT of BNB", "Buy 20.123 USDT of BNB", "Buy 0 USDT of BNB", None, 20]:
            with self.subTest(message=message), self.assertRaises(InvalidRequest):
                parse_request(message)
        self.assertEqual(parse_request("please buy 20 USDT worth of BNB."), ("BNBUSDT", Decimal("20.00")))

    def test_invalid_money_is_rejected(self):
        for value in ["NaN", "Infinity", "-1", "1000001", "1.001", True, None, [], "no"]:
            with self.subTest(value=value), self.assertRaises(InvalidRequest):
                money(value)

    def test_unknown_preview_and_invalid_rules(self):
        with self.assertRaises(InvalidRequest):
            self.engine.approve("missing")
        for pairs in ["BNBUSDT", [{}], ["SOLUSDT"]]:
            with self.subTest(pairs=pairs), self.assertRaises(InvalidRequest):
                self.rules(allowed_pairs=pairs)

    def test_database_survives_restart(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        reopened = Engine(self.engine.database, clock=lambda: self.now)
        self.assertEqual(reopened.state()["balance"], "104.98")
        self.assertEqual(len(reopened.state()["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
