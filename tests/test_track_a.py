import copy
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import Mock

from backend.engine import Engine, InvalidRequest
from backend.advisor import FixtureAdvisor, OpenAIAdvisor, validate_advisory, AdvisoryError
from backend.agentos import research_data
from backend.market_analysis import format_evidence_for_prompt
from backend.news import parse_rss


class TrackATests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.now = 1800000000
        self.engine = Engine(Path(self.tmp.name) / "test.db", clock=lambda: self.now)

    def test_model_receives_identified_market_and_news_evidence(self):
        response = FixtureAdvisor().advise("paper", "BNBUSDT", "short", "", {}, {}, [])
        transport = Mock(return_value={"status": "completed", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": json.dumps(response)}]}]})
        self.engine.advisor = OpenAIAdvisor("test-model", transport)
        self.engine.market_analyzer = Mock()
        self.engine.market_analyzer.evidence.return_value = {"id": "market-test", "source": "test", "retrieved_at": self.now,
            "close_time": self.now, "fresh": True, "symbol": "BNBUSDT", "horizon": "short", "recent_return_pct": "1",
            "trend": "up", "volatility_pct": "2", "drawdown_pct": "0", "volume_change_pct": "3"}
        advice = self.engine.advise({"symbol": "BNBUSDT"})
        self.assertIn("market-test", advice["evidence_ids"])
        self.assertIn("Available cash: 125.00", transport.call_args.args[0]["input"][0]["content"])

    def test_advice_preview_requires_supported_action_and_fresh_advice(self):
        output = FixtureAdvisor().advise("paper", "BNBUSDT", "short", "", {}, {}, [])
        output["recommendation"] = "BUY"
        self.engine.advisor = FixtureAdvisor(output)
        advice = self.engine.advise({"symbol": "BNBUSDT"})
        preview = self.engine.advice_preview(advice["id"], {"amount": "20"})
        self.assertEqual(preview["advisory_id"], advice["id"])
        self.assertEqual(self.engine.state()["balance"], "125.00")
        self.now += 601
        with self.assertRaises(InvalidRequest):
            self.engine.advice_preview(advice["id"], {"amount": "20"})

    def test_historical_report_never_uses_current_price(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        self.now += 2 * 86400
        calc = self.engine.generate_report({"report_type": "daily", "period": "completed"})["calculations"]
        self.assertEqual(calc["closing_value"], "Unavailable")
        self.assertEqual(calc["total_pnl"], "Unavailable")
        self.assertEqual(calc["coverage"], "partial")

    def test_disabled_buy_market_can_be_sold_and_pnl_reconciles(self):
        self.engine.approve(self.engine.preview("Buy 20 USDT of BNB")["id"])
        qty = self.engine.state()["holdings"]["BNB"]
        self.engine.save_rules({"daily_limit": "50", "reserve": "125", "allowed_pairs": []})
        sale = self.engine.approve(self.engine.preview({"side": "SELL", "symbol": "BNBUSDT", "quantity": qty})["id"])
        self.assertEqual(sale["trade"]["side"], "SELL")
        state = self.engine.state()
        self.assertEqual(state["spent_today"], "20.02")
        self.assertEqual(self.engine.portfolio.holdings("paper")["realized_pnl"], Decimal(state["balance"]) - 125)

    def test_schedule_failure_retries_once_and_restart_deduplicates(self):
        schedule = self.engine.upsert_schedule({"report_type": "daily", "local_time": "12:00"})
        self.now = schedule["next_run"] + 1
        runner = Mock(side_effect=[RuntimeError("temporary"), {"id": "ok"}])
        self.engine.scheduler.tick(runner)
        self.now += 301
        self.engine.scheduler.tick(runner)
        self.engine.scheduler.tick(runner)
        self.assertEqual(runner.call_count, 2)

    def test_private_publication_idempotency(self):
        schedule = self.engine.upsert_schedule({"report_type": "daily"})
        self.now = schedule["next_run"] + 1
        self.engine.run_due_schedules()
        self.engine.run_due_schedules()
        self.assertEqual(len(self.engine.list_reports()), 1)
        with self.engine.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM report_publications").fetchone()[0], 1)

    def test_missing_news_date_is_not_retrieval_date(self):
        rss = '<rss><channel><item><title>Bitcoin</title><link>https://example.com/news</link></item></channel></rss>'
        self.assertEqual(parse_rss(rss, "test", ["BTC"], lambda: self.now), [])

    def test_null_agentos_research_is_not_successful_evidence(self):
        self.assertIsNone(research_data({"structuredContent": {"success": True},
            "content": [{"type": "text", "text": '{"data": null}'}]}))

    def test_unknown_citation_is_rejected(self):
        result = FixtureAdvisor().advise("paper", "BNBUSDT", "short", "", {}, {}, [])
        result["opposing_factors"] = ["news-invented"]
        with self.assertRaises(AdvisoryError):
            validate_advisory(result, ["quote-BNBUSDT"])
