"""Fixed public Spot research reads through the genuine Codex host.

The reviewed operation has no read-only annotation; this adapter explicitly
allows only analysis.getTokenAiReport. It never exposes generic execution.
"""
import json
import hashlib
from decimal import Decimal
import threading
import time
from pathlib import Path

from backend.codex_mcp import CodexHost, discover_binance
from backend.mcp import AccountUnavailable, result_data

RESEARCH_TOOL = "analysis.getTokenAiReport"
RESEARCH_SCHEMA = "cd4616a9282ca5664ab80d6b76aff87d04b710041a849ad140f9ff53f0f6b61f"


def research_data(result):
    if not isinstance(result, dict) or result.get("isError"):
        raise AccountUnavailable("Agent OS research request failed.")
    # Text can preserve explicit null data omitted from structuredContent.
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                value = json.loads(block["text"])
                if isinstance(value, dict) and "data" in value:
                    return value["data"]
            except (ValueError, KeyError):
                continue
    value = result.get("structuredContent")
    return value.get("data") if isinstance(value, dict) else None


class AgentOSResearch:
    def __init__(self, factory=CodexHost, clock=time.time):
        self.factory, self.clock = factory, clock
        self.host = None
        self.thread_id = None
        self.lock = threading.Lock()
        self.cache = {}

    def close(self):
        if self.host:
            self.host.close()
            self.host = None

    def evidence(self, symbol):
        if symbol not in {"BNBUSDT", "BTCUSDT", "ETHUSDT"}:
            raise ValueError("Unsupported Spot research symbol.")
        with self.lock:
            now = self.clock()
            cached = self.cache.get(symbol)
            if cached and now < cached[0]:
                return cached[1]
            result = {"id": f"agentos-{symbol}-{int(now)}", "type": "agentos_research",
                      "source": "Binance Agent OS", "symbol": symbol, "retrieved_at": now}
            try:
                if self.host is None:
                    self.host = self.factory()
                    self.host.initialize()
                    inventory = discover_binance(self.host.rpc)
                    definition = next((t for t in inventory["tools"] if t["name"] == RESEARCH_TOOL), None)
                    if not definition or definition["schema_sha256"] != RESEARCH_SCHEMA:
                        raise AccountUnavailable("Agent OS research capability changed; review is required.")
                    self.thread_id = self.host._request("thread/start", {
                        "ephemeral": True, "cwd": str(Path.cwd()),
                        "approvalPolicy": "never", "sandbox": "read-only"})["thread"]["id"]
                raw = self.host._request("mcpServer/tool/call", {
                    "threadId": self.thread_id, "server": "binance", "tool": RESEARCH_TOOL,
                    "arguments": {"token": symbol.removesuffix("USDT"), "product": "spot"}})
                data = research_data(raw)
                if not data:
                    raise AccountUnavailable("Agent OS returned no research for this token.")
                # Retain as unverified until the live report identity/time schema is reviewed.
                result.update({"status": "unverified", "error": "Research returned, but token and publication-time validation is pending."})
            except (AccountUnavailable, OSError, ValueError, KeyError) as exc:
                result.update({"status": "unavailable", "error": str(exc)})
                self.close()
            self.cache[symbol] = (now + 300, result)
            return result


class AgentOSMarket(AgentOSResearch):
    """Explicitly reviewed Spot price read; no account data or order tools."""
    def evidence(self, symbol):
        if symbol not in {"BNBUSDT", "BTCUSDT", "ETHUSDT"}:
            raise ValueError("Unsupported Spot symbol.")
        with self.lock:
            now = self.clock()
            cached = self.cache.get(symbol)
            if cached and now < cached[0]:
                return cached[1]
            result = {"id": f"agentos-{symbol}-{int(now)}", "type": "agentos_market",
                      "source": "Binance Agent OS · Spot", "symbol": symbol, "retrieved_at": now}
            try:
                if self.host is None:
                    self.host = self.factory()
                    self.host.initialize()
                    inventory = discover_binance(self.host.rpc)
                    pins = {"tool_execute": "432cebf61a0f35b1477a63405ef840adb2faa9a329972268bbd95050e07401a3",
                            "tool_search": "baa645b1e0f09c90ce0c3ea858ae7f3543a560c3b4aeb49ee83f4052bcde4abc"}
                    for name, pin in pins.items():
                        if not any(t["name"] == name and t["schema_sha256"] == pin for t in inventory["tools"]):
                            raise AccountUnavailable("Agent OS wrapper schema changed; review required.")
                    self.thread_id = self.host._request("thread/start", {"ephemeral": True,
                        "cwd": str(Path.cwd()), "approvalPolicy": "never", "sandbox": "read-only"})["thread"]["id"]
                    cursor, seen, reviewed = None, set(), False
                    for _ in range(10):
                        args = {"category": "market"}
                        if cursor:
                            args["cursor"] = cursor
                        page = result_data(self.host._request("mcpServer/tool/call", {
                            "threadId": self.thread_id, "server": "binance", "tool": "tool_search", "arguments": args}), [])
                        if isinstance(page, str):
                            page = json.loads(page)
                        for definition in page.get("tools", []):
                            if definition.get("name") == "spot.tickerPrice":
                                digest = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                                reviewed = digest == "62c6c4a3fd0fc5e30ecab01fe0f43b65ca1e0e530269fcbe04021febe79f4f4f"
                        cursor = page.get("nextCursor")
                        if not cursor or reviewed:
                            break
                        if not isinstance(cursor, str) or cursor in seen:
                            raise AccountUnavailable("Agent OS discovery pagination failed.")
                        seen.add(cursor)
                    if not reviewed:
                        raise AccountUnavailable("Reviewed Agent OS Spot price capability unavailable or changed.")
                data = result_data(self.host._request("mcpServer/tool/call", {
                    "threadId": self.thread_id, "server": "binance", "tool": "tool_execute",
                    "arguments": {"toolName": "spot.tickerPrice", "arguments": {"symbol": symbol}}}), [])
                if not isinstance(data, dict) or data.get("symbol") != symbol:
                    raise AccountUnavailable("Agent OS returned the wrong Spot symbol.")
                price_text = data.get("price")
                if not isinstance(price_text, str) or len(price_text) > 40:
                    raise AccountUnavailable("Invalid Agent OS Spot price.")
                price = Decimal(price_text)
                if not price.is_finite() or price <= 0:
                    raise AccountUnavailable("Invalid Agent OS Spot price.")
                result.update({"status": "ready", "price": str(price), "retrieved_at": self.clock(),
                               "expires_at": self.clock() + 60})
            except (AccountUnavailable, OSError, ValueError, KeyError, ArithmeticError) as exc:
                result.update({"status": "unavailable", "error": str(exc)})
                self.close()
            self.cache[symbol] = (self.clock() + 30, result)
            return result


if __name__ == "__main__":
    service = AgentOSMarket()
    try:
        for symbol in ("BNBUSDT", "BTCUSDT", "ETHUSDT"):
            print(json.dumps(service.evidence(symbol)), flush=True)
    finally:
        service.close()
