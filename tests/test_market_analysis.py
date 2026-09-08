import unittest

from backend.market_analysis import MarketAnalyzer, build_evidence, Candle


def rising_candles(n):
    rows = []
    for i in range(n):
        price = 100 + i
        rows.append(Candle([i * 3600000, str(price), str(price + 1), str(price - 1), str(price), str(1000 + i), (i + 1) * 3600000 - 1, "0", "0", "0", "0", "0"]))
    return rows


class MarketAnalysisTests(unittest.TestCase):
    def test_build_evidence_computes_interpretable_indicators(self):
        candles = rising_candles(40)
        ev = build_evidence("BNBUSDT", "short", candles, 1000)
        self.assertEqual(ev["symbol"], "BNBUSDT")
        self.assertEqual(float(ev["recent_return_pct"]) > 0, True)
        self.assertEqual(ev["trend"], "up")
        self.assertEqual(ev["candles"], 40)

    def test_analyzer_caches_results(self):
        calls = []
        def fetch(symbol, interval, limit):
            calls.append((symbol, interval, limit))
            return [
                [0, "100", "105", "99", "100", "1000", 0, "0", "0", "0", "0", "0"],
                [0, "100", "106", "99", "101", "1100", 0, "0", "0", "0", "0", "0"],
            ]
        analyzer = MarketAnalyzer(fetch=fetch, clock=lambda: 1000)
        analyzer.evidence("BNBUSDT", "short")
        analyzer.evidence("BNBUSDT", "short")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
