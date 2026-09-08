import queue
import unittest
from unittest.mock import Mock

from backend.codex_mcp import CodexHost, discover_binance
from backend.mcp import AccountUnavailable


class CodexDiscoveryTests(unittest.TestCase):
    def test_authenticated_paginated_inventory(self):
        tool = {"name": "example", "inputSchema": {"type": "object"}}
        rpc = Mock(side_effect=[{"data": [], "nextCursor": "page2"}, {"data": [
            {"name": "binance", "authStatus": "oAuth", "tools": {"example": tool}}]}])
        result = discover_binance(rpc)
        self.assertEqual(result["tools"][0]["name"], "example")
        self.assertEqual(len(result["tools"][0]["schema_sha256"]), 64)
        self.assertEqual(rpc.call_args.args[1]["cursor"], "page2")

    def test_missing_or_unauthorized_or_invalid_inventory(self):
        for page in [{"data": []}, {"data": [{"name": "binance", "authStatus": "notLoggedIn"}]},
                     {"data": [{"name": "binance", "authStatus": "oAuth", "tools": {"x": {"name": "y"}}}]}, {}]:
            with self.subTest(page=page), self.assertRaises(AccountUnavailable):
                discover_binance(Mock(return_value=page))

    def test_repeated_cursor_fails(self):
        with self.assertRaises(AccountUnavailable):
            discover_binance(Mock(return_value={"data": [], "nextCursor": "same"}))

    def host(self):
        host = CodexHost.__new__(CodexHost)
        host.sequence = 0
        host.messages = queue.Queue()
        host.send = Mock()
        return host

    def test_discovery_cannot_call_tools_or_start_agent(self):
        host = self.host()
        for method in ["mcpServer/tool/call", "turn/start", "account/read"]:
            with self.assertRaises(AccountUnavailable):
                host.rpc(method, {})
        host.send.assert_not_called()

    def test_interactive_request_is_rejected(self):
        host = self.host()
        host.messages.put({"id": 42, "method": "mcpServer/elicitation/request"})
        host.messages.put({"id": 1, "result": {"data": []}})
        self.assertEqual(host.rpc("mcpServerStatus/list", {}), {"data": []})
        self.assertEqual(host.send.call_args.args[0]["error"]["code"], -32601)

    def test_disconnect_and_server_error_fail(self):
        for message in [None, {"id": 1, "error": {"message": "private detail"}}]:
            host = self.host()
            host.messages.put(message)
            with self.assertRaises(AccountUnavailable) as error:
                host.rpc("initialize", {})
            self.assertNotIn("private detail", str(error.exception))
