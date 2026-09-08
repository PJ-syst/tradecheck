import copy
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from backend.engine import Engine, InvalidRequest
from backend.market import BinanceMarket, MarketUnavailable, fetch_prices
from market_fixtures import public_response


def prices():
    return [{"symbol": "BNBUSDT", "price": "650.00"},
            {"symbol": "BTCUSDT", "price": "100000.00"},
            {"symbol": "ETHUSDT", "price": "3500.00"}]


class MarketTests(unittest.TestCase):
    def setUp(self):
        mocked = patch("backend.market.fetch_public", side_effect=public_response)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.now = 1800000000
        self.calls = 0
        self.payload = prices()
        self.failure = None
        self.market = BinanceMarket(self.fetch, lambda: self.now)

    def fetch(self):
        self.calls += 1
        if self.failure:
            raise self.failure
        return copy.deepcopy(self.payload)

    def test_public_transport_has_only_supported_symbols_and_no_credentials(self):
        with patch("backend.market.urlopen") as opened:
            opened.return_value.__enter__.return_value.read.return_value = b'[]'
            self.assertEqual(fetch_prices(), [])
        request = opened.call_args.args[0]
        parsed = urlparse(request.full_url)
        self.assertEqual(parsed.netloc, "data-api.binance.vision")
        self.assertEqual(parsed.path, "/api/v3/ticker/price")
        self.assertEqual(set(parse_qs(parsed.query)), {"symbols"})
        self.assertFalse(request.has_header("X-mbx-apikey"))
        self.assertEqual(opened.call_args.kwargs["timeout"], 5)

    def test_exchange_symbols_are_compact_for_binance_parameter_validation(self):
        with patch("backend.market.fetch_public", return_value=public_response("exchangeInfo", {})) as fetch:
            market = BinanceMarket(fetch=prices, clock=lambda: self.now)
            market.quote("BNBUSDT")
        self.assertNotIn(" ", fetch.call_args.args[1]["symbols"])

    def test_cache_is_shared_and_cannot_be_mutated_by_callers(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: self.market.snapshot(), range(4)))
        self.assertEqual(self.calls, 1)
        rows[0][0]["price"] = "1"
        self.assertEqual(self.market.quote("BNBUSDT")["price"], "650.00")
        self.now += 15
        self.market.snapshot()
        self.assertEqual(self.calls, 2)

    def test_failure_clears_prices_and_backs_off_then_recovers(self):
        self.market.snapshot()
        self.now += 15
        self.failure = URLError("offline")
        for _ in range(3):
            with self.assertRaises(MarketUnavailable):
                self.market.snapshot()
        self.assertEqual(self.calls, 2)
        self.now += 30
        self.failure = None
        self.assertEqual(self.market.quote("BTCUSDT")["price"], "100000.00")

    def test_rate_limit_honors_retry_after(self):
        self.failure = HTTPError("https://example.invalid", 429, "rate limited", {"Retry-After": "300"}, io.BytesIO())
        with self.assertRaisesRegex(MarketUnavailable, "429"):
            self.market.snapshot()
        self.failure = None
        self.now += 299
        with self.assertRaises(MarketUnavailable):
            self.market.snapshot()
        self.assertEqual(self.calls, 1)
        self.now += 1
        self.market.snapshot()
        self.assertEqual(self.calls, 2)

    def test_malformed_data_never_becomes_a_quote(self):
        invalid = [None, {}, [], prices()[:2], [prices()[0]] * 3,
                   [None] * 3]
        for value in ["NaN", "Infinity", "0", "-2", "1e999", True, 650]:
            payload = prices()
            payload[0]["price"] = value
            invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload):
                market = BinanceMarket(lambda: payload, lambda: self.now)
                with self.assertRaises(MarketUnavailable):
                    market.snapshot()

    def test_slow_response_is_rejected(self):
        def slow():
            self.now += 60
            return prices()
        with self.assertRaises(MarketUnavailable):
            BinanceMarket(slow, lambda: self.now).snapshot()


class LivePaperTests(unittest.TestCase):
    def setUp(self):
        mocked = patch("backend.market.fetch_public", side_effect=public_response)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000
        self.payload = prices()
        self.market = BinanceMarket(lambda: self.payload, lambda: self.now)
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3", clock=lambda: self.now, market=self.market)

    def test_preview_uses_live_price_and_approval_keeps_reviewed_quote(self):
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.assertEqual(preview["price"], "650.00")
        self.assertEqual(preview["expires_at"], self.now + 60)
        self.payload[0]["price"] = "700.00"
        self.now += 15
        self.assertEqual(self.engine.state()["markets"][0]["price"], "700.00")
        trade = self.engine.approve(preview["id"])["trade"]
        self.assertEqual(trade["quantity"], preview["quantity"])
        self.assertEqual(trade["price"], "650.00")
        self.assertEqual(trade["balance_after"], "104.98")
        self.now += 120
        self.assertTrue(self.engine.approve(preview["id"])["already_executed"])

    def test_cached_quote_age_limits_preview_lifetime(self):
        self.market.snapshot()
        self.now += 10
        preview = self.engine.preview("Buy 20 USDT of BNB")
        self.assertEqual(preview["expires_at"] - self.now, 50)
        self.now += 50
        with self.assertRaisesRegex(InvalidRequest, "expired"):
            self.engine.approve(preview["id"])
        self.assertEqual(self.engine.state()["balance"], "125.00")

    def test_source_change_invalidates_preview_across_restart(self):
        fixture = Engine(self.engine.database, clock=lambda: self.now)
        preview = fixture.preview("Buy 20 USDT of BNB")
        with self.assertRaisesRegex(InvalidRequest, "source changed"):
            self.engine.approve(preview["id"])
        live_preview = self.engine.preview("Buy 20 USDT of BNB")
        with self.assertRaisesRegex(InvalidRequest, "source changed"):
            fixture.approve(live_preview["id"])

    def test_outage_preserves_wallet_and_does_not_fall_back(self):
        self.market.fetch = lambda: None
        state = self.engine.state()
        self.assertEqual(state["market_data"]["status"], "unavailable")
        self.assertEqual(state["markets"], [])
        self.assertEqual(state["balance"], "125.00")
        with self.assertRaises(MarketUnavailable):
            self.engine.preview("Buy 20 USDT of BNB")
        self.assertEqual(self.engine.state()["events"], [])
