import copy
import json
import io
from email.message import Message
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.engine import Engine
from backend.mcp import MCPClient, ReadOnlyAccount, AccountUnavailable, schema_hash, result_data


def tool(name):
    # Synthetic test tools, not assumed Binance tool names.
    return {"name": name, "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True, "destructiveHint": False}}


class FakeClient:
    def __init__(self):
        self.tools = [tool("test_balances"), tool("test_commissions")]
        self.calls = []
        self.invalid_balance = False

    def discover(self):
        return self.tools

    def rpc(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if params["name"] == "test_balances":
            data = [{"asset": "USDT", "free": "NaN" if self.invalid_balance else "999.25", "locked": "3"}]
        else:
            data = {"symbol": params["arguments"]["symbol"], **{category: {key: "0.001" for key in ("maker", "taker", "buyer", "seller")}
                     for category in ("standardCommission", "specialCommission", "taxCommission")}}
        return {"structuredContent": data}


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.now = 1800000000
        def spec(name, args):
            definition = next(t for t in self.client.tools if t["name"] == name)
            return {"tool": name, "schema_sha256": schema_hash(definition), "arguments": args, "result_path": []}
        self.manifest = {"balances": spec("test_balances", {}),
                         "commissions": {symbol: spec("test_commissions", {"symbol": symbol}) for symbol in ("BNBUSDT", "BTCUSDT", "ETHUSDT")}}
        self.account = ReadOnlyAccount(self.manifest, lambda: self.client, lambda: self.now)

    def test_explicit_refresh_only_and_paper_wallet_separation(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(Path(folder) / "test.db", account=self.account)
            self.assertEqual(engine.state()["account"]["status"], "not connected")
            self.assertEqual(self.client.calls, [])
            snapshot = self.account.snapshot(refresh=True)
            self.assertEqual(snapshot["status"], "connected")
            self.assertEqual(len(self.client.calls), 4)
            state = engine.state()
            self.assertEqual(state["balance"], "125.00")
            self.assertEqual(state["account"]["balances"][0]["free"], "999.25")
            self.assertEqual(engine.preview("Buy 20 USDT of BNB")["fee"], "0.02")
            self.assertNotIn("999.25", Path(engine.database).read_bytes().decode("latin1"))

    def test_changed_schema_or_write_tool_blocks_all_account_calls(self):
        for mutation in [lambda t: t["inputSchema"].update({"required": ["new_field"]}),
                         lambda t: t["annotations"].update({"readOnlyHint": False}),
                         lambda t: t["annotations"].update({"destructiveHint": True})]:
            self.setUp()
            mutation(self.client.tools[1])
            self.assertEqual(self.account.snapshot(refresh=True)["status"], "unavailable")
            self.assertEqual(self.client.calls, [])

    def test_invalid_data_clears_display_and_cache_expires(self):
        snapshot = self.account.snapshot(refresh=True)
        snapshot["balances"][0]["free"] = "1"
        self.assertEqual(self.account.snapshot()["balances"][0]["free"], "999.25")
        self.now += 60
        self.assertEqual(self.account.snapshot()["status"], "stale")
        self.client.invalid_balance = True
        snapshot = self.account.snapshot(refresh=True)
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["balances"], [])

    def test_fixed_arguments_cannot_be_changed_after_construction(self):
        self.manifest["commissions"]["BNBUSDT"]["arguments"]["symbol"] = "EVIL"
        self.assertEqual(self.account.snapshot(refresh=True)["status"], "connected")
        self.assertEqual(self.client.calls[1][1]["arguments"], {"symbol": "BNBUSDT"})

    def test_missing_token_does_not_send_request(self):
        with patch.dict("os.environ", {}, clear=True), patch("backend.credentials.load", return_value={}), patch("backend.mcp.build_opener") as opened:
            with self.assertRaisesRegex(AccountUnavailable, "not connected"):
                MCPClient().discover()
            opened.assert_not_called()

    def test_tool_error_and_wrong_rpc_id_are_rejected(self):
        with self.assertRaises(AccountUnavailable):
            result_data({"isError": True, "structuredContent": {}}, [])
        with self.assertRaises(AccountUnavailable):
            MCPClient._result({"jsonrpc": "2.0", "id": 8, "result": {}}, 7)
        self.assertEqual(result_data({"content": [{"type": "text", "text": '{"balances": []}'}]}, ["balances"]), [])

    def test_transport_accepts_json_and_sse_and_preserves_session(self):
        for content_type in ("application/json", "text/event-stream"):
            with self.subTest(content_type=content_type), patch.dict("os.environ", {"BINANCE_MCP_TOKEN": "synthetic-test-token"}), patch("backend.mcp.build_opener") as opened:
                headers = Message()
                headers["Content-Type"] = content_type
                headers["Mcp-Session-Id"] = "synthetic-session"
                message = '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
                body = io.BytesIO(("event: message\ndata: " + message + "\n\n").encode() if content_type == "text/event-stream" else message.encode())
                body.headers = headers
                opened.return_value.open.return_value = body
                client = MCPClient()
                self.assertEqual(client.rpc("tools/list"), {"tools": []})
                self.assertEqual(client.session, "synthetic-session")
                request = opened.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, "https://agent.binance.com/mcp/agentic")
                self.assertEqual(json.loads(request.data)["method"], "tools/list")

    def test_rate_limit_backoff_prevents_repeated_calls(self):
        def limited():
            raise AccountUnavailable("Rate limited", 300)
        self.client.discover = limited
        self.account.snapshot(refresh=True)
        self.client.discover = lambda: self.client.tools
        self.now += 299
        self.assertEqual(self.account.snapshot(refresh=True)["status"], "unavailable")
        self.now += 1
        self.assertEqual(self.account.snapshot(refresh=True)["status"], "connected")
