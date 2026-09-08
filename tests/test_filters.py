import copy
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError

from backend.filters import exchange_symbols, estimate
from backend.engine import Engine, InvalidRequest
from backend.market import BinanceMarket, MarketUnavailable
from market_fixtures import exchange_info


class FilterTests(unittest.TestCase):
    def metadata(self, step="0.003", minimum="5", mins=0):
        return exchange_symbols(exchange_info(step, minimum, mins))["BNBUSDT"]

    def test_rounds_to_step_multiple_not_decimal_places(self):
        quantity, checks = estimate(Decimal("20"), Decimal("600"), self.metadata())
        self.assertEqual(quantity, Decimal("0.033"))
        self.assertTrue(all(c["pass"] for c in checks))

    def test_common_increment_satisfies_both_quantity_filters(self):
        metadata = self.metadata()
        metadata["filters"][1]["stepSize"] = "0.002"
        quantity, _ = estimate(Decimal("20"), Decimal("600"), metadata)
        self.assertEqual(quantity, Decimal("0.030"))

    def test_rounding_can_put_notional_below_minimum(self):
        _, checks = estimate(Decimal("5"), Decimal("600"), self.metadata())
        self.assertFalse(next(c["pass"] for c in checks if c["name"] == "MIN_NOTIONAL"))

    def test_average_price_flags_and_window(self):
        metadata = self.metadata(mins=5)
        metadata["average"] = {"price": "100", "mins": 5}
        _, checks = estimate(Decimal("20"), Decimal("600"), metadata)
        self.assertFalse(next(c["pass"] for c in checks if c["name"] == "MIN_NOTIONAL"))
        metadata["filters"][2]["applyToMarket"] = False
        _, checks = estimate(Decimal("20"), Decimal("600"), metadata)
        self.assertTrue(all(c["pass"] for c in checks))
        metadata["filters"][2]["applyToMarket"] = True
        metadata["average"]["mins"] = 1
        with self.assertRaises(MarketUnavailable):
            estimate(Decimal("20"), Decimal("600"), metadata)

    def test_max_notional_position_and_unknown_filters_block(self):
        for row in [
            {"filterType": "NOTIONAL", "minNotional": "0", "maxNotional": "10", "applyMinToMarket": False, "applyMaxToMarket": True, "avgPriceMins": 0},
            {"filterType": "MAX_POSITION", "maxPosition": "0.04"},
            {"filterType": "NEW_CONSTRAINT"},
            {"filterType": "EXCHANGE_MAX_NUM_ORDERS", "maxNumOrders": 0},
        ]:
            metadata = self.metadata()
            metadata["filters"].append(row)
            _, checks = estimate(Decimal("20"), Decimal("600"), metadata, Decimal("0.02"))
            self.assertFalse(checks[-1]["pass"])

    def test_status_market_permission_and_quantity_bounds(self):
        for field, value in [("status", "HALT"), ("spot", False), ("market", False)]:
            metadata = self.metadata()
            metadata[field] = value
            self.assertFalse(estimate(Decimal("20"), Decimal("600"), metadata)[1][0]["pass"])
        metadata = self.metadata()
        metadata["filters"][1]["maxQty"] = "0.01"
        self.assertFalse(all(c["pass"] for c in estimate(Decimal("20"), Decimal("600"), metadata)[1]))

    def test_invalid_metadata_is_rejected(self):
        for value in [None, {}, {"symbols": []}]:
            with self.assertRaises(MarketUnavailable):
                exchange_symbols(value)
        for value in ["NaN", "-1", "1e-100", "Infinity", True]:
            payload = exchange_info()
            payload["symbols"][0]["filters"][0]["stepSize"] = value
            with self.assertRaises(MarketUnavailable):
                exchange_symbols(payload)

    def test_paper_debit_reflects_rounded_purchase_and_filter_expiry(self):
        now = [1800000000]
        market = BinanceMarket(fetch=lambda: [{"symbol": s["symbol"], "price": "600"} for s in exchange_info()["symbols"]],
                               clock=lambda: now[0], fetch_info=lambda: exchange_info("0.003"))
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(Path(folder) / "test.db", market=market, clock=lambda: now[0])
            preview = engine.preview("Buy 20 USDT of BNB")
            self.assertEqual(preview["purchase_cost"], "19.80")
            self.assertEqual(preview["unspent_amount"], "0.20")
            self.assertEqual(engine.approve(preview["id"])["trade"]["balance_after"], "105.18")

    def test_filters_unavailable_never_falls_back_to_demo(self):
        def fail():
            raise URLError("offline")
        market = BinanceMarket(fetch=lambda: [{"symbol": s["symbol"], "price": "600"} for s in exchange_info()["symbols"]], fetch_info=fail)
        with self.assertRaises(MarketUnavailable):
            market.quote("BNBUSDT")
