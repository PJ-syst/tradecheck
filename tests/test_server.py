import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.engine import Engine
from backend.server import make_server
from backend.market import BinanceMarket
from backend.interpreter import OpenAIInterpreter


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(Path(self.temp.name) / "test.sqlite3")
        self.server = make_server(self.engine, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.request("/api/state")[1]["csrf_token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, token=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-TradeCheck-Token"] = token
        if origin:
            headers["Origin"] = origin
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_http_purchase_and_duplicate_approval(self):
        status, preview = self.request("/api/preview", {"message": "Buy 20 USDT of BNB"}, self.token)
        self.assertEqual(status, 200)
        self.assertTrue(preview["allowed"])
        status, result = self.request("/api/approve", {"preview_id": preview["id"]}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(result["trade"]["balance_after"], "104.98")
        _, duplicate = self.request("/api/approve", {"preview_id": preview["id"]}, self.token)
        self.assertTrue(duplicate["already_executed"])

    def test_mutations_require_token_and_local_origin(self):
        self.assertEqual(self.request("/api/preview", {"message": "Buy 20 USDT of BNB"})[0], 403)
        self.assertEqual(self.request("/api/preview", {"message": "Buy 20 USDT of BNB"}, self.token, "https://example.com")[0], 403)

    def test_bad_payloads_and_absent_endpoints(self):
        self.assertEqual(self.request("/api/preview", [], self.token)[0], 400)
        self.assertEqual(self.request("/api/preview", {}, self.token)[0], 400)
        self.assertEqual(self.request("/api/real-order", {}, self.token)[0], 404)
        self.assertEqual(self.request("/api/health")[1]["mode"], "paper")

    def test_market_outage_is_visible_and_preview_returns_503(self):
        self.engine.market = BinanceMarket(fetch=lambda: None)
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["market_data"]["status"], "unavailable")
        self.assertEqual(state["markets"], [])
        status, result = self.request("/api/preview", {"message": "Buy 20 USDT of BNB"}, self.token)
        self.assertEqual(status, 503)
        self.assertIn("market data", result["error"])

    def test_rule_proposal_is_not_a_save_and_account_refresh_requires_token(self):
        self.engine.interpreter = OpenAIInterpreter("test-model", lambda _: {
            "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": json.dumps({"clarification": None, "daily_limit": "75", "reserve": None, "allowed_pairs": None})}]}]})
        status, proposal = self.request("/api/rules/propose", {"message": "Set daily budget to 75 USDT"}, self.token)
        self.assertEqual(status, 200)
        self.assertTrue(proposal["requires_confirmation"])
        self.assertEqual(self.engine.state()["rules"]["daily_limit"], "50.00")
        self.assertEqual(self.request("/api/rules", proposal["rules"], self.token)[0], 200)
        self.assertEqual(self.request("/api/account/refresh", {})[0], 403)
        self.assertEqual(self.request("/api/account/refresh", {}, self.token)[1]["status"], "not connected")


if __name__ == "__main__":
    unittest.main()
