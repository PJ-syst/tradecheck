"""Spot candle analysis and interpretable indicators. No model reasoning here."""

import json
import math
import threading
import time
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.market import PAIRS, MarketUnavailable


INTERVAL_HORIZON = {
    "short": ("1h", 24),    # last 24 hours
    "medium": ("1h", 168),  # last 7 days
    "long": ("1d", 60),     # last 60 days
}

CACHE_SECONDS = 60


def fetch_klines(symbol, interval, limit):
    query = urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    request = Request(
        "https://data-api.binance.vision/api/v3/klines?" + query,
        headers={"Accept": "application/json", "User-Agent": "TradeCheck/0.3"},
    )
    with urlopen(request, timeout=10) as response:
        body = response.read(1048577)
        if len(body) > 1048576:
            raise MarketUnavailable("Candle response too large.")
        return json.loads(body)


def _to_decimal(value):
    if not isinstance(value, str) or len(value) > 40:
        raise MarketUnavailable("Invalid candle field.")
    number = Decimal(value)
    if not number.is_finite() or number <= 0:
        raise MarketUnavailable("Invalid candle field.")
    return number


class Candle:
    def __init__(self, row):
        if not isinstance(row, (list, tuple)) or len(row) < 9:
            raise MarketUnavailable("Invalid candle row.")
        if not isinstance(row[0], int) or not isinstance(row[6], int):
            raise MarketUnavailable("Invalid candle timestamps.")
        self.open_time = row[0] // 1000
        self.close_time = row[6] // 1000
        self.open = _to_decimal(row[1])
        self.high = _to_decimal(row[2])
        self.low = _to_decimal(row[3])
        self.close = _to_decimal(row[4])
        self.volume = _to_decimal(row[5])


class MarketAnalyzer:
    def __init__(self, fetch=None, clock=None):
        self.fetch = fetch or fetch_klines
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._cache = {}

    def evidence(self, symbol, horizon="short"):
        if symbol not in PAIRS:
            raise InvalidAnalysisRequest("Unsupported symbol.")
        if horizon not in INTERVAL_HORIZON:
            raise InvalidAnalysisRequest("Unsupported horizon.")
        interval, limit = INTERVAL_HORIZON[horizon]
        cache_key = (symbol, interval, limit)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and self.clock() < cached["expires_at"]:
                return cached["value"]
        candles = self._load(symbol, interval, limit)
        result = build_evidence(symbol, horizon, candles, self.clock())
        with self._lock:
            self._cache[cache_key] = {"expires_at": self.clock() + CACHE_SECONDS, "value": result}
        return result

    def _load(self, symbol, interval, limit):
        try:
            payload = self.fetch(symbol, interval, limit)
        except (HTTPError, URLError, OSError, ValueError, InvalidOperation) as exc:
            raise MarketUnavailable("Candle data unavailable.") from exc
        if not isinstance(payload, list) or not payload:
            raise MarketUnavailable("Invalid candle response.")
        candles = []
        for row in payload:
            try:
                candles.append(Candle(row))
            except (MarketUnavailable, InvalidOperation):
                raise MarketUnavailable("Invalid candle data.")
        return candles


class InvalidAnalysisRequest(ValueError):
    pass


def build_evidence(symbol, horizon, candles, now):
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    if len(closes) < 2:
        raise MarketUnavailable("Insufficient candle history.")
    start_price, end_price = closes[0], closes[-1]
    recent_return = ((end_price / start_price) - Decimal("1")) * Decimal("100")
    highest = max(closes)
    lowest = min(closes)
    peak, drawdown = closes[0], Decimal("0")
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, (close / peak - 1) * 100)
    returns = []
    for i in range(1, len(closes)):
        returns.append(float((closes[i] / closes[i - 1]) - Decimal("1")))
    volatility = Decimal(str(math.sqrt(sum(r * r for r in returns) / len(returns)))) * Decimal("100") if returns else Decimal("0")
    sma_short_len = min(12, len(closes))
    sma_long_len = min(26, len(closes))
    sma_short = sum(closes[-sma_short_len:]) / Decimal(sma_short_len)
    sma_long = sum(closes[-sma_long_len:]) / Decimal(sma_long_len)
    trend = "up" if sma_short > sma_long else "down" if sma_short < sma_long else "flat"
    mid = len(volumes) // 2
    avg_recent_volume = sum(volumes[mid:]) / Decimal(max(1, len(volumes) - mid))
    avg_older_volume = sum(volumes[:mid]) / Decimal(max(1, mid))
    volume_change = Decimal("0")
    if avg_older_volume > 0:
        volume_change = ((avg_recent_volume / avg_older_volume) - Decimal("1")) * Decimal("100")
    return {
        "id": f"market-{symbol}-{horizon}-{int(now)}",
        "source": "Binance public klines",
        "symbol": symbol,
        "horizon": horizon,
        "interval": INTERVAL_HORIZON[horizon][0],
        "candles": len(candles),
        "open_time": candles[0].open_time,
        "close_time": candles[-1].close_time,
        "retrieved_at": now,
        "start_price": str(start_price),
        "end_price": str(end_price),
        "recent_return_pct": str(recent_return.quantize(Decimal("0.01"))),
        "trend": trend,
        "ma_short": str(sma_short.quantize(Decimal("0.01"))),
        "ma_long": str(sma_long.quantize(Decimal("0.01"))),
        "volatility_pct": str(volatility.quantize(Decimal("0.01"))),
        "drawdown_pct": str(drawdown.quantize(Decimal("0.01"))),
        "volume_change_pct": str(volume_change.quantize(Decimal("0.01"))),
        "fresh": 0 <= now - candles[-1].open_time <= (7200 if INTERVAL_HORIZON[horizon][0] == "1h" else 172800),
    }


def format_evidence_for_prompt(evidence):
    return {
        "type": "market_analysis",
        "evidence_id": evidence["id"],
        "id": evidence["id"],
        "source": evidence["source"],
        "retrieved_at": evidence["retrieved_at"],
        "close_time": evidence["close_time"],
        "fresh": evidence["fresh"],
        "symbol": evidence["symbol"],
        "horizon": evidence["horizon"],
        "recent_return_pct": evidence["recent_return_pct"],
        "trend": evidence["trend"],
        "volatility_pct": evidence["volatility_pct"],
        "drawdown_pct": evidence["drawdown_pct"],
        "volume_change_pct": evidence["volume_change_pct"],
    }
