"""Public price providers. No credentials, account access, or order endpoints."""

import copy
import json
import threading
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PAIRS = {"BNBUSDT": "600", "BTCUSDT": "90000", "ETHUSDT": "3000"}
QUOTE_TTL = 60
CACHE_SECONDS = 15
RETRY_SECONDS = 30


class MarketUnavailable(ValueError):
    pass


class FixtureMarket:
    name = "fixture"
    source = "demo fixture"

    def snapshot(self):
        return [{"symbol": symbol, "price": price, "source": self.source,
                 "provider": self.name, "observed_at": None, "expires_at": None}
                for symbol, price in PAIRS.items()]

    def quote(self, symbol):
        return next(row for row in self.snapshot() if row["symbol"] == symbol)


def fetch_prices():
    query = urlencode({"symbols": json.dumps(list(PAIRS), separators=(",", ":"))})
    request = Request("https://data-api.binance.vision/api/v3/ticker/price?" + query,
                      headers={"Accept": "application/json", "User-Agent": "TradeCheck/0.2"})
    with urlopen(request, timeout=5) as response:
        body = response.read(65537)
        if len(body) > 65536:
            raise MarketUnavailable("Binance returned an oversized price response.")
        return json.loads(body)


def fetch_public(path, params):
    request = Request("https://data-api.binance.vision/api/v3/" + path + "?" + urlencode(params),
                      headers={"Accept": "application/json", "User-Agent": "TradeCheck/0.3"})
    with urlopen(request, timeout=5) as response:
        body = response.read(262145)
        if len(body) > 262144:
            raise MarketUnavailable("Exchange response is too large.")
        return json.loads(body)


class BinanceMarket(FixtureMarket):
    name = "binance"
    source = "Binance public API"

    def __init__(self, fetch=None, clock=None, fetch_info=None, fetch_average=None):
        self.fetch = fetch or fetch_prices
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._rows = []
        self._next_fetch = 0
        self._error = None
        self.fetch_info = fetch_info or (lambda: fetch_public("exchangeInfo", {"symbols": json.dumps(list(PAIRS), separators=(",", ":"))}))
        self.fetch_average = fetch_average or (lambda symbol: fetch_public("avgPrice", {"symbol": symbol}))
        self._info_lock = threading.Lock()
        self._metadata = {}
        self._info_expiry = 0
        self._info_retry = 0

    def quote(self, symbol):
        from backend.filters import exchange_symbols, decimal_value
        quote = super().quote(symbol)
        with self._info_lock:
            now = self.clock()
            if now < self._info_retry:
                raise MarketUnavailable("Exchange filters unavailable. Retry shortly.")
            try:
                if now >= self._info_expiry:
                    self._metadata = exchange_symbols(self.fetch_info())
                    self._info_expiry = now + 300
                metadata = copy.deepcopy(self._metadata[symbol])
                needed = any(row["filterType"] in {"MIN_NOTIONAL", "NOTIONAL"} and row["avgPriceMins"] > 0
                             for row in metadata["filters"])
                if needed:
                    average = self.fetch_average(symbol)
                    if not isinstance(average, dict) or type(average.get("mins")) is not int or decimal_value(average.get("price")) <= 0:
                        raise MarketUnavailable("Invalid average-price response.")
                    metadata["average"] = {"mins": average["mins"], "price": average["price"]}
                quote["constraints"] = metadata
                quote["expires_at"] = min(quote["expires_at"], self._info_expiry)
                return quote
            except (ValueError, OSError, InvalidOperation, TypeError, KeyError) as exc:
                self._metadata = {}
                self._info_expiry = 0
                delay = 30
                if isinstance(exc, HTTPError):
                    if exc.code in {418, 429}:
                        try:
                            delay = max(120, int(exc.headers.get("Retry-After", "120")))
                        except (TypeError, ValueError):
                            delay = 120
                    exc.close()
                self._info_retry = self.clock() + delay
                raise MarketUnavailable("Exchange filters or average price unavailable. Retry shortly.") from None

    def snapshot(self):
        with self._lock:
            now = self.clock()
            if now < self._next_fetch:
                if self._error:
                    raise MarketUnavailable(self._error)
                if self._rows and now < self._rows[0]["expires_at"]:
                    return copy.deepcopy(self._rows)
            try:
                payload = self.fetch()
                if not isinstance(payload, list) or len(payload) != len(PAIRS):
                    raise ValueError("Unexpected symbols")
                prices = {}
                for item in payload:
                    if not isinstance(item, dict):
                        raise ValueError("Unexpected price row")
                    symbol, value = item.get("symbol"), item.get("price")
                    if not isinstance(symbol, str) or symbol not in PAIRS or symbol in prices:
                        raise ValueError("Unexpected symbol")
                    if not isinstance(value, str) or len(value) > 40:
                        raise ValueError("Unexpected price")
                    price = Decimal(value)
                    if not price.is_finite() or not Decimal("0.00000001") <= price <= Decimal("1000000000"):
                        raise ValueError("Invalid price")
                    prices[symbol] = str(price)
                if self.clock() >= now + QUOTE_TTL:
                    raise MarketUnavailable("Binance prices arrived too late. Refresh markets to retry.")
                self._rows = [{"symbol": symbol, "price": prices[symbol],
                               "provider": self.name, "source": self.source,
                               "observed_at": now, "expires_at": now + QUOTE_TTL}
                              for symbol in PAIRS]
                self._error = None
                self._next_fetch = now + CACHE_SECONDS
                return copy.deepcopy(self._rows)
            except HTTPError as exc:
                self._error = f"Binance market data unavailable (HTTP {exc.code})."
                delay = 120 if exc.code in {418, 429} else RETRY_SECONDS
                if exc.code in {418, 429}:
                    try:
                        delay = max(delay, int(exc.headers.get("Retry-After", "120")))
                    except (ValueError, TypeError):
                        pass
                exc.close()
            except (URLError, OSError):
                self._error = "Cannot reach Binance market data. Check your connection and retry."
                delay = RETRY_SECONDS
            except (ValueError, InvalidOperation):
                self._error = "Binance returned invalid or expired market data. Refresh markets to retry."
                delay = RETRY_SECONDS
            self._rows = []
            self._next_fetch = self.clock() + delay
            raise MarketUnavailable(self._error)
