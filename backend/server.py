"""Loopback-only JSON API and production frontend hosting."""

import argparse
import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.engine import Engine, InvalidRequest
from backend.market import BinanceMarket, FixtureMarket, MarketUnavailable
from backend.interpreter import OpenAIInterpreter, StrictInterpreter, InterpreterUnavailable
from backend.mcp import ReadOnlyAccount, DisconnectedAccount
from backend.advisor import OpenAIAdvisor, FixtureAdvisor
from backend.reports import ReportError
from backend.news import NewsAggregator

ROOT = Path(__file__).resolve().parents[1]


def make_server(engine, port=8000):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return urlparse("http://" + self.headers.get("Host", "")).hostname in {"localhost", "127.0.0.1"}

        def _path_parts(self, prefix):
            path = urlparse(self.path).path
            if not path.startswith(prefix):
                return None
            rest = path[len(prefix):].strip("/")
            return rest.split("/") if rest else []

        def _download_format(self):
            from urllib.parse import parse_qs
            query = parse_qs(urlparse(self.path).query)
            fmt = (query.get("format", ["markdown"]) or ["markdown"])[0]
            return fmt if fmt in {"html", "markdown", "json"} else "markdown"

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Local access only."})
            path = urlparse(self.path).path
            if path == "/api/state":
                return self.reply(200, {**engine.state(), "csrf_token": token})
            if path == "/api/health":
                return self.reply(200, {"status": "ok", "mode": "paper"})
            if path == "/api/reports":
                return self.reply(200, {"reports": engine.list_reports()})
            if path == "/api/report-schedules":
                return self.reply(200, {"schedules": engine.list_schedules()})
            parts = self._path_parts("/api/reports/")
            if parts and len(parts) == 1:
                report_id = parts[0]
                try:
                    result = engine.get_report(report_id)
                    return self.reply(200, result)
                except ReportError as exc:
                    return self.reply(404, {"error": str(exc)})
            if parts and len(parts) == 2 and parts[1] == "download":
                report_id, fmt = parts[0], self._download_format()
                try:
                    body = engine.get_report(report_id, format=fmt)
                    content_type = {"html": "text/html", "markdown": "text/markdown", "json": "application/json"}.get(fmt, "text/plain")
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Disposition", 'attachment; filename="portfolio-report.' + {"html": "html", "markdown": "md", "json": "json"}[fmt] + '"')
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body.encode("utf-8"))
                    return
                except ReportError as exc:
                    return self.reply(404, {"error": str(exc)})
            if path.startswith("/api/"):
                return self.reply(404, {"error": "Endpoint not found."})
            dist = (ROOT / "dist").resolve()
            target = (dist / (path.lstrip("/") or "index.html")).resolve()
            if not target.is_relative_to(dist) or not target.is_file():
                return self.reply(404, {"error": "Frontend not found. Run npm run build or use the Vite development server."})
            data = target.read_bytes()
            self.send_response(200)
            content_type = "text/javascript" if target.suffix == ".js" else mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-TradeCheck-Token") != token:
                return self.reply(403, {"error": "Refresh this local dashboard before making changes."})
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://127.0.0.1:5173", "http://localhost:5173", f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.reply(403, {"error": "Origin not allowed."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "Send application/json."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise InvalidRequest("Request body must be between 1 and 65536 bytes.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise InvalidRequest("Request must be a JSON object.")
                path = urlparse(self.path).path
                if path == "/api/preview":
                    result = engine.preview(payload)
                elif path == "/api/approve":
                    result = engine.approve(payload.get("preview_id"))
                elif path == "/api/rules":
                    result = engine.save_rules(payload)
                elif path == "/api/rules/propose":
                    result = engine.propose_rules(payload.get("message"))
                elif path == "/api/account/refresh":
                    result = engine.account.snapshot(refresh=True)
                elif path == "/api/advice":
                    result = engine.advise(payload)
                elif path.startswith("/api/advice/") and path.endswith("/preview"):
                    result = engine.advice_preview(path.split("/")[3], payload)
                elif path == "/api/reports":
                    result = engine.generate_report(payload)
                elif path == "/api/report-schedules":
                    result = engine.upsert_schedule(payload)
                else:
                    parts = self._path_parts("/api/report-schedules/")
                    if parts and len(parts) == 1:
                        action = payload.get("action")
                        if action == "pause":
                            result = engine.pause_schedule(parts[0]); result = {"status": "paused"}
                        elif action == "enable":
                            result = engine.enable_schedule(parts[0]); result = {"status": "enabled"}
                        elif action == "run":
                            result = {"outcomes": engine.run_due_schedules()}
                        else:
                            return self.reply(400, {"error": "Missing action."})
                    else:
                        return self.reply(404, {"error": "Endpoint not found."})
                self.reply(200, result)
            except (MarketUnavailable, InterpreterUnavailable) as exc:
                self.reply(503, {"error": str(exc)})
            except (InvalidRequest, ValueError, UnicodeDecodeError) as exc:
                self.reply(400, {"error": str(exc)})
            except Exception:
                self.log_error("Unexpected API error")
                self.reply(500, {"error": "The local service could not complete this request."})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="TradeCheck paper-trading server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "tradecheck.sqlite3")
    parser.add_argument("--market-data", choices=["fixture", "binance"], default="fixture",
                        help="Price source for paper purchases (default: fixture)")
    parser.add_argument("--interpreter", choices=["strict", "openai"], default="strict")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--news-config", type=Path, default=ROOT / "data" / "news-config.json")
    parser.add_argument("--agentos", "--agentos-research", dest="agentos_research", action="store_true", help="Read public Spot prices through the existing Codex Binance login")
    parser.add_argument("--mcp-manifest", type=Path, help="Reviewed, pinned read-only MCP account tool configuration")
    args = parser.parse_args()
    if args.interpreter == "openai" and not args.model:
        model_config = ROOT / "data" / "model.json"
        if model_config.exists():
            try:
                args.model = json.loads(model_config.read_text(encoding="utf-8"))["model"]
            except (ValueError, KeyError, TypeError):
                parser.error("Saved model configuration is invalid. Run python -m backend.setup again.")
    market = BinanceMarket() if args.market_data == "binance" else FixtureMarket()
    try:
        interpreter = OpenAIInterpreter(args.model) if args.interpreter == "openai" else StrictInterpreter()
        advisor = OpenAIAdvisor(args.model) if args.interpreter == "openai" else FixtureAdvisor()
        account = ReadOnlyAccount(json.loads(args.mcp_manifest.read_text(encoding="utf-8"))) if args.mcp_manifest else DisconnectedAccount()
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    news_config = json.loads(args.news_config.read_text(encoding="utf-8")) if args.news_config.exists() else {}
    from backend.agentos import AgentOSMarket
    research = AgentOSMarket() if args.agentos_research else None
    engine = Engine(args.database, market=market, interpreter=interpreter, account=account, advisor=advisor,
                    news=NewsAggregator(news_config), research=research)
    server = make_server(engine, args.port)

    def scheduler_loop():
        while True:
            try:
                engine.capture_snapshot()
                engine.run_due_schedules()
            except Exception as exc:
                print(f"Portfolio worker: {type(exc).__name__}; retrying in 60 seconds.", flush=True)
            time.sleep(60)
    threading.Thread(target=scheduler_loop, daemon=True).start()

    print(f"TradeCheck: http://127.0.0.1:{args.port} (paper mode, {market.source})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if research:
            research.close()


if __name__ == "__main__":
    main()
