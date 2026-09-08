"""Pinned, read-only MCP account adapter. Tool names must come from discovery.

Authentication is supplied by an external authorized MCP/OAuth setup through
BINANCE_MCP_TOKEN. No tokens or account responses are persisted by this module.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from backend.filters import decimal_value
from backend.interpreter import NoRedirect

ENDPOINT = "https://agent.binance.com/mcp/agentic"
PROTOCOL = "2025-06-18"


class AccountUnavailable(ValueError):
    def __init__(self, message, retry_after=15):
        super().__init__(message)
        self.retry_after = retry_after


def schema_hash(tool):
    return hashlib.sha256(json.dumps({"inputSchema": tool.get("inputSchema"), "annotations": tool.get("annotations")},
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MCPClient:
    def __init__(self):
        self.session = None
        self.sequence = 0

    def rpc(self, method, params=None, notification=False):
        token = os.environ.get("BINANCE_MCP_TOKEN")
        if not token:
            from backend.credentials import load
            try:
                stored = load("binance")
            except ValueError as exc:
                raise AccountUnavailable(str(exc)) from None
            if stored.get("resource") == ENDPOINT and time.time() < stored.get("expires_at", 0):
                token = stored.get("access_token")
        if not token:
            raise AccountUnavailable("Binance account is not connected. Complete MCP authorization and configure the server token.")
        self.sequence += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            payload["id"] = self.sequence
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json", "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers=headers)
        try:
            with build_opener(NoRedirect()).open(request, timeout=10) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session = session
                if notification:
                    return None
                if response.headers.get_content_type() == "text/event-stream":
                    total, data = 0, []
                    for raw in response:
                        total += len(raw)
                        if total > 262144:
                            raise ValueError("Oversized stream")
                        line = raw.decode().rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            message = json.loads("\n".join(data))
                            data = []
                            if message.get("id") == payload["id"]:
                                return self._result(message, payload["id"])
                    raise ValueError("Missing RPC response")
                body = response.read(262145)
                if len(body) > 262144:
                    raise ValueError("Oversized response")
                return self._result(json.loads(body), payload["id"])
        except HTTPError as exc:
            code = exc.code
            delay = 15
            if code in {418, 429}:
                try:
                    delay = max(120, int(exc.headers.get("Retry-After", "120")))
                except (TypeError, ValueError):
                    delay = 120
            exc.close()
            if code in {401, 403}:
                raise AccountUnavailable("Binance authorization expired or lacks Account scope. Reconnect with read-only account permission.") from None
            raise AccountUnavailable(f"Binance MCP returned HTTP {code}. Retry later.", delay) from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise AccountUnavailable("Binance MCP returned an unavailable or invalid response.") from None

    @staticmethod
    def _result(message, expected_id):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != expected_id or "error" in message or "result" not in message:
            raise AccountUnavailable("Binance MCP request failed or returned an unexpected response.")
        return message["result"]

    def discover(self):
        result = self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                       "clientInfo": {"name": "TradeCheck", "version": "0.3"}})
        if not isinstance(result, dict) or result.get("protocolVersion") != PROTOCOL:
            raise AccountUnavailable("MCP protocol version is not supported by this client.")
        self.rpc("notifications/initialized", notification=True)
        tools, cursor, seen = [], None, set()
        for _ in range(20):
            page = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
                raise AccountUnavailable("MCP discovery returned invalid tools.")
            tools.extend(page["tools"])
            cursor = page.get("nextCursor")
            if not cursor:
                if any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str) for tool in tools):
                    raise AccountUnavailable("Invalid MCP tool names.")
                if len({tool["name"] for tool in tools}) != len(tools):
                    raise AccountUnavailable("Duplicate MCP tool names.")
                return tools
            if not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
        raise AccountUnavailable("MCP discovery did not complete.")


def result_data(result, path):
    if not isinstance(result, dict) or result.get("isError"):
        raise AccountUnavailable("Binance account tool could not complete the request.")
    data = result.get("structuredContent")
    if data is None:
        blocks = result.get("content", [])
        if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get("type") != "text":
            raise AccountUnavailable("Account tool returned an unsupported result.")
        data = json.loads(blocks[0]["text"])
    for key in path:
        data = data[key]
    return data


class DisconnectedAccount:
    def snapshot(self, refresh=False):
        return {"status": "not connected", "source": "Binance MCP", "balances": [], "commissions": {},
                "observed_at": None, "expires_at": None, "error": None}


class ReadOnlyAccount:
    def __init__(self, manifest, client_factory=None, clock=None):
        if not isinstance(manifest, dict) or set(manifest) != {"balances", "commissions"}:
            raise ValueError("MCP manifest must define balances and commissions.")
        if not isinstance(manifest["commissions"], dict) or set(manifest["commissions"]) != {"BNBUSDT", "BTCUSDT", "ETHUSDT"}:
            raise ValueError("MCP manifest must define commission reads for all three supported pairs.")
        for spec in [manifest["balances"], *manifest["commissions"].values()]:
            if not isinstance(spec, dict) or set(spec) != {"tool", "schema_sha256", "arguments", "result_path"}:
                raise ValueError("Each MCP read must specify tool, schema_sha256, arguments, and result_path.")
            if not isinstance(spec["tool"], str) or not isinstance(spec["schema_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", spec["schema_sha256"]):
                raise ValueError("MCP reads require a discovered tool name and pinned schema hash.")
            if not isinstance(spec["arguments"], dict) or not isinstance(spec["result_path"], list) or any(not isinstance(k, str) for k in spec["result_path"]):
                raise ValueError("Invalid fixed MCP arguments or result path.")
        self.manifest = copy.deepcopy(manifest)
        self.factory = client_factory or MCPClient
        self.clock = clock or time.time
        self.lock = threading.Lock()
        self.cached = DisconnectedAccount().snapshot()
        self.retry_at = 0

    def snapshot(self, refresh=False):
        with self.lock:
            now = self.clock()
            if not refresh or now < self.retry_at:
                result = copy.deepcopy(self.cached)
                if result["expires_at"] is not None and now >= result["expires_at"] and result["status"] == "connected":
                    result["status"] = "stale"
                return result
            try:
                retry_delay = 15
                client = self.factory()
                tools = {tool["name"]: tool for tool in client.discover()}
                # Validate every pinned capability before issuing any account read.
                for spec in [self.manifest["balances"], *self.manifest["commissions"].values()]:
                    tool = tools.get(spec["tool"])
                    if not tool or tool.get("annotations", {}).get("readOnlyHint") is not True or tool.get("annotations", {}).get("destructiveHint") is True or schema_hash(tool) != spec["schema_sha256"]:
                        raise AccountUnavailable("A configured MCP tool is missing, changed, or not marked read-only. Review discovery before reconnecting.")

                def read(spec):
                    return result_data(client.rpc("tools/call", {"name": spec["tool"], "arguments": spec["arguments"]}), spec["result_path"])

                balances = read(self.manifest["balances"])
                if not isinstance(balances, list) or len(balances) > 10000:
                    raise ValueError("Invalid balances")
                normalized, seen = [], set()
                for row in balances:
                    asset = row["asset"]
                    if not isinstance(asset, str) or not re.fullmatch(r"[A-Z0-9]{1,30}", asset) or asset in seen:
                        raise ValueError("Invalid asset")
                    seen.add(asset)
                    free, locked = decimal_value(row["free"]), decimal_value(row["locked"])
                    if free or locked:
                        normalized.append({"asset": asset, "free": str(free), "locked": str(locked)})
                commissions = {}
                for symbol, spec in self.manifest["commissions"].items():
                    result = read(spec)
                    if result.get("symbol") != symbol:
                        raise ValueError("Commission symbol mismatch")
                    rates = {}
                    for category in ("standardCommission", "specialCommission", "taxCommission"):
                        rates[category] = {key: str(decimal_value(result[category][key])) for key in ("maker", "taker", "buyer", "seller")}
                    # Discounts and fee assets depend on account settings; do not turn these rates into a paper fee.
                    commissions[symbol] = rates
                self.cached = {"status": "connected", "source": "Binance MCP · read-only", "balances": normalized,
                               "commissions": commissions, "observed_at": now, "expires_at": now + 60, "error": None}
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                retry_delay = exc.retry_after if isinstance(exc, AccountUnavailable) else 15
                self.cached = {**DisconnectedAccount().snapshot(), "status": "unavailable",
                               "error": str(exc) if isinstance(exc, AccountUnavailable) else "Binance account data was invalid. Check the read-only manifest."}
            self.retry_at = self.clock() + retry_delay
            return copy.deepcopy(self.cached)


def main():
    parser = argparse.ArgumentParser(description="Discover Binance MCP tools without calling account or trading tools")
    parser.add_argument("--discover", type=Path, required=True)
    args = parser.parse_args()
    try:
        tools = MCPClient().discover()
        result = [{**tool, "schema_sha256": schema_hash(tool)} for tool in tools]
        args.discover.parent.mkdir(parents=True, exist_ok=True)
        args.discover.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Saved {len(result)} tool definitions to {args.discover}; no account or trading tools called.")
    except AccountUnavailable as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
