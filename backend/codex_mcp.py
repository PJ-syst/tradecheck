"""Discover Binance through the genuine Codex host; never read its credentials."""

import argparse
import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from backend.mcp import AccountUnavailable, schema_hash


class CodexHost:
    def __init__(self):
        executable = shutil.which("codex")
        if not executable:
            raise AccountUnavailable("Install Codex CLI and run codex mcp login binance first.")
        self.process = subprocess.Popen(
            [executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.messages = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def rpc(self, method, params):
        # This diagnostic cannot start model turns or call MCP tools.
        if method not in {"initialize", "mcpServerStatus/list"}:
            raise AccountUnavailable("Only connection discovery is supported.")
        self.sequence += 1
        request_id = self.sequence
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 60
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise AccountUnavailable("Codex discovery timed out. Check the Binance connection in Codex.") from None
            if not isinstance(message, dict):
                raise AccountUnavailable("Codex host disconnected during discovery.")
            if "method" in message:
                if "id" in message:
                    self.send({"jsonrpc": "2.0", "id": message["id"], "error": {
                        "code": -32601, "message": "Interactive requests unavailable in discovery"}})
                continue
            if message.get("id") == request_id:
                if "error" in message or "result" not in message:
                    raise AccountUnavailable("Codex rejected discovery. Update Codex and check its Binance login.")
                return message["result"]

    def initialize(self):
        self.rpc("initialize", {"clientInfo": {
            "name": "tradecheck", "title": "TradeCheck", "version": "0.3"},
            "capabilities": {"experimentalApi": True}})
        self.send({"jsonrpc": "2.0", "method": "initialized"})

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def discover_binance(rpc):
    cursor, seen = None, set()
    for _ in range(20):
        params = {"detail": "toolsAndAuthOnly", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = rpc("mcpServerStatus/list", params)
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise AccountUnavailable("Codex returned an invalid server inventory.")
        for server in page["data"]:
            if not isinstance(server, dict) or server.get("name") != "binance":
                continue
            tools = server.get("tools")
            if server.get("authStatus") != "oAuth":
                raise AccountUnavailable("Run codex mcp login binance to authorize the supported host.")
            if not isinstance(tools, dict) or any(
                    not isinstance(t, dict) or t.get("name") != name or
                    not isinstance(t.get("inputSchema"), dict) for name, t in tools.items()):
                raise AccountUnavailable("Codex returned invalid Binance tool definitions.")
            return {"server": "binance", "auth_status": "oAuth", "tools": [
                {**tool, "schema_sha256": schema_hash(tool)} for tool in tools.values()]}
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if not isinstance(cursor, str) or cursor in seen:
            raise AccountUnavailable("Codex server pagination did not complete.")
        seen.add(cursor)
    raise AccountUnavailable("Binance is missing from the Codex inventory. Run codex mcp add binance --url https://agent.binance.com/mcp/agentic.")


def main():
    parser = argparse.ArgumentParser(description="Check supported Codex/Binance login and save tool definitions; no tool calls")
    parser.add_argument("--discover", type=Path, default=Path("data/codex-binance-tools.json"))
    args = parser.parse_args()
    host = None
    try:
        host = CodexHost()
        host.initialize()
        result = discover_binance(host.rpc)
        args.discover.parent.mkdir(parents=True, exist_ok=True)
        args.discover.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Codex Binance OAuth connected. Saved {len(result['tools'])} tool definitions to {args.discover}.")
        print("No account or trading tools called. This does not activate the dashboard account panel.")
    except (AccountUnavailable, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        if host:
            host.close()


if __name__ == "__main__":
    main()
