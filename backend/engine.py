"""Deterministic policy checks and atomic paper fills. No real trading APIs."""

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from pathlib import Path

from backend.market import FixtureMarket, MarketUnavailable, PAIRS
from backend.interpreter import StrictInterpreter
from backend.filters import estimate
from backend.mcp import DisconnectedAccount
FEE_RATE = Decimal("0.001")
CENT = Decimal("0.01")
PREVIEW_TTL = 120


class InvalidRequest(ValueError):
    pass


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InvalidRequest("Enter a valid amount with up to two decimal places.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise InvalidRequest("Enter a valid amount.") from None
    if not number.is_finite() or number < 0 or number > 1_000_000:
        raise InvalidRequest("Amount must be between 0 and 1,000,000 USDT.")
    if number != number.quantize(CENT):
        raise InvalidRequest("Use at most two decimal places for USDT amounts.")
    return number.quantize(CENT)


def fmt(value):
    return str(value.quantize(CENT))


def parse_request(message):
    if not isinstance(message, str) or len(message) > 200:
        raise InvalidRequest("Use a short request, such as: Buy 20 USDT of BNB.")
    match = re.fullmatch(
        r"\s*(?:please\s+)?buy\s+([0-9]+(?:\.[0-9]{1,2})?)\s+USDT\s+(?:of|worth of)\s+(BNB|BTC|ETH)(?:/USDT|USDT)?\s*[.!]?\s*",
        message, re.IGNORECASE,
    )
    if not match:
        raise InvalidRequest("Try: Buy 20 USDT of BNB. This prototype supports one BNB, BTC, or ETH purchase per request.")
    amount = money(match[1])
    if amount <= 0:
        raise InvalidRequest("Purchase amount must be greater than zero.")
    return match[2].upper() + "USDT", amount


class Engine:
    def __init__(self, database, clock=None, market=None, interpreter=None, account=None):
        self.database = str(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self.market = market or FixtureMarket()
        self.interpreter = interpreter or StrictInterpreter()
        self.account = account or DisconnectedAccount()
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY CHECK(id=1), balance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS previews (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, preview_id TEXT UNIQUE NOT NULL, day TEXT NOT NULL, total TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
            """)
            conn.execute("INSERT OR IGNORE INTO wallet VALUES (1, '125.00')")
            conn.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (json.dumps({
                "daily_limit": "50.00", "reserve": "100.00", "allowed_pairs": list(PAIRS), "version": 1,
            }),))

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def day(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()

    def _state(self, conn):
        rules = json.loads(conn.execute("SELECT data FROM settings WHERE id=1").fetchone()[0])
        balance = Decimal(conn.execute("SELECT balance FROM wallet WHERE id=1").fetchone()[0])
        spent = sum((Decimal(row[0]) for row in conn.execute("SELECT total FROM trades WHERE day=?", (self.day(),))), Decimal(0))
        return rules, balance, spent

    def _event(self, conn, kind, title, detail):
        conn.execute("INSERT INTO events (data) VALUES (?)", (json.dumps({
            "kind": kind, "title": title, "detail": detail, "timestamp": self.clock(),
        }),))

    def state(self):
        market_error = None
        try:
            markets = self.market.snapshot()
        except MarketUnavailable as exc:
            markets, market_error = [], str(exc)
        with self.connection() as conn:
            rules, balance, spent = self._state(conn)
            trades = [json.loads(row[0]) for row in conn.execute("SELECT data FROM trades ORDER BY rowid DESC")]
            holdings = {}
            for trade in trades:
                asset = trade["symbol"].removesuffix("USDT")
                holdings[asset] = str(Decimal(holdings.get(asset, "0")) + Decimal(trade["quantity"]))
            return {
                "mode": "paper", "rules": rules, "balance": fmt(balance), "spent_today": fmt(spent),
                "remaining_budget": fmt(max(Decimal(0), Decimal(rules["daily_limit"]) - spent)),
                "day": self.day(), "holdings": holdings, "trades": trades[:30],
                "markets": markets,
                "market_data": {"provider": self.market.name, "source": self.market.source,
                                "status": "unavailable" if market_error else "ready", "error": market_error},
                "events": [json.loads(row[0]) for row in conn.execute("SELECT data FROM events ORDER BY id DESC LIMIT 30")],
                "supported_pairs": list(PAIRS),
                "account": self.account.snapshot(),
                "integration": {"binance_mcp": "not connected", "interpreter": self.interpreter.name},
            }

    def save_rules(self, payload):
        limit, reserve = money(payload.get("daily_limit")), money(payload.get("reserve"))
        allowed = payload.get("allowed_pairs")
        if not isinstance(allowed, list) or any(not isinstance(x, str) or x not in PAIRS for x in allowed):
            raise InvalidRequest("Allowed pairs must be a list of supported symbols.")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old, _, _ = self._state(conn)
            if "version" in payload and (type(payload["version"]) is not int or payload["version"] != old["version"]):
                raise InvalidRequest("Rules changed while you were editing. Reopen the editor or request a new proposal.")
            rules = {"daily_limit": fmt(limit), "reserve": fmt(reserve), "allowed_pairs": sorted(set(allowed)), "version": old["version"] + 1}
            conn.execute("UPDATE settings SET data=? WHERE id=1", (json.dumps(rules),))
            self._event(conn, "rules", "Trading rules updated", "Existing previews now require a fresh check.")
        return rules

    def propose_rules(self, message):
        with self.connection() as conn:
            current, _, _ = self._state(conn)
        return {"rules": self.interpreter.rules(message, current), "requires_confirmation": True}

    def _evaluate(self, conn, symbol, amount, quote):
        rules, balance, spent = self._state(conn)
        quantity = (amount / Decimal(quote["price"])).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        exchange_checks = []
        purchase_cost = amount
        if "constraints" in quote:
            holding = sum((Decimal(json.loads(row[0])["quantity"]) for row in conn.execute("SELECT data FROM trades")
                           if json.loads(row[0])["symbol"] == symbol), Decimal(0))
            quantity, exchange_checks = estimate(amount, Decimal(quote["price"]), quote["constraints"], holding)
            purchase_cost = (quantity * Decimal(quote["price"])).quantize(CENT, rounding=ROUND_UP)
        fee = (purchase_cost * FEE_RATE).quantize(CENT, rounding=ROUND_UP)
        total = purchase_cost + fee
        headroom = max(Decimal(0), min(balance - Decimal(rules["reserve"]), Decimal(rules["daily_limit"]) - spent, balance))
        maximum = (headroom / (1 + FEE_RATE)).quantize(CENT, rounding=ROUND_DOWN)
        checks = [
            {"name": "Allowed market", "pass": symbol in rules["allowed_pairs"], "detail": f"{symbol.removesuffix('USDT')}/USDT must be enabled in your rules."},
            {"name": "Demo order minimum", "pass": amount >= Decimal("5"), "detail": "Paper orders start at 5.00 USDT; actual exchange filters are not connected."},
            {"name": "Available funds", "pass": total <= balance, "detail": f"{fmt(total)} USDT including fees / {fmt(balance)} USDT available."},
            {"name": "Daily spending limit", "pass": spent + total <= Decimal(rules["daily_limit"]), "detail": f"{fmt(spent + total)} / {rules['daily_limit']} USDT today, including fees (UTC)."},
            {"name": "Protected reserve", "pass": balance - total >= Decimal(rules["reserve"]), "detail": f"{fmt(balance - total)} USDT after purchase / {rules['reserve']} USDT minimum."},
        ]
        if exchange_checks:
            checks = [checks[0], *exchange_checks, *checks[2:]]
        passed = all(check["pass"] for check in checks)
        can_suggest = maximum >= 5 and symbol in rules["allowed_pairs"]
        if "constraints" in quote and can_suggest:
            _, suggested_checks = estimate(maximum, Decimal(quote["price"]), quote["constraints"], holding)
            can_suggest = all(check["pass"] for check in suggested_checks)
        return {
            "symbol": symbol, "amount": fmt(amount), "fee": fmt(fee), "total": fmt(total),
            "price": quote["price"], "quantity": str(quantity), "purchase_cost": fmt(purchase_cost),
            "unspent_amount": fmt(amount - purchase_cost), "filter_source": "Binance exchangeInfo" if exchange_checks else "demo minimum",
            "balance_before": fmt(balance), "balance_after": fmt(balance - total),
            "checks": checks, "allowed": passed, "maximum": fmt(maximum) if can_suggest else "0.00",
            "rules_version": rules["version"], "day": self.day(), "price_source": quote["source"], "mode": "paper",
            "quote": quote,
        }

    def preview(self, message):
        intent = self.interpreter.trade(message)
        symbol, amount = intent["symbol"], money(intent["amount"])
        if symbol not in PAIRS or amount <= 0:
            raise InvalidRequest("Invalid purchase proposal.")
        quote = self.market.quote(symbol)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = self.clock()
            if quote["expires_at"] is not None and now >= quote["expires_at"]:
                raise MarketUnavailable("Market quote expired. Check your request again.")
            result = self._evaluate(conn, symbol, amount, quote)
            expiry = min(now + PREVIEW_TTL, quote["expires_at"]) if quote["expires_at"] is not None else now + PREVIEW_TTL
            result.update({"id": str(uuid.uuid4()), "created_at": now, "expires_at": expiry})
            conn.execute("INSERT INTO previews VALUES (?, ?)", (result["id"], json.dumps(result)))
            self._event(conn, "passed" if result["allowed"] else "blocked", "Purchase checked" if result["allowed"] else "Purchase blocked", f"Buy {result['amount']} USDT of {symbol.removesuffix('USDT')}")
        return result

    def approve(self, preview_id):
        if not isinstance(preview_id, str) or len(preview_id) > 100:
            raise InvalidRequest("A valid preview ID is required.")
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT data FROM trades WHERE preview_id=?", (preview_id,)).fetchone()
            if previous:
                return {"trade": json.loads(previous[0]), "already_executed": True}
            row = conn.execute("SELECT data FROM previews WHERE id=?", (preview_id,)).fetchone()
            if not row:
                raise InvalidRequest("Preview not found. Check your request again.")
            preview = json.loads(row[0])
            if not preview["allowed"]:
                raise InvalidRequest("This purchase was blocked. Create a new preview.")
            if self.clock() >= preview["expires_at"] or self.day() != preview["day"]:
                raise InvalidRequest("This preview expired. Check your request again.")
            # Legacy previews were created with fixtures. Never silently change their price source.
            quote = preview.get("quote") or FixtureMarket().quote(preview["symbol"])
            if quote["provider"] == "binance" and "constraints" not in quote:
                raise InvalidRequest("Preview predates exchange-filter checks. Check your request again.")
            if quote["provider"] != self.market.name:
                raise InvalidRequest("Market data source changed. Check your request again.")
            if quote["expires_at"] is not None and self.clock() >= quote["expires_at"]:
                raise InvalidRequest("Market quote expired. Check your request again.")
            current = self._evaluate(conn, preview["symbol"], Decimal(preview["amount"]), quote)
            if current["rules_version"] != preview["rules_version"] or current["balance_before"] != preview["balance_before"] or not current["allowed"]:
                raise InvalidRequest("Your rules or balance changed. Check your request again before approval.")
            trade = {**current, "id": "paper-" + str(uuid.uuid4())[:12], "preview_id": preview_id, "timestamp": self.clock()}
            conn.execute("UPDATE wallet SET balance=? WHERE id=1", (current["balance_after"],))
            conn.execute("INSERT INTO trades VALUES (?, ?, ?, ?, ?)", (trade["id"], preview_id, self.day(), current["total"], json.dumps(trade)))
            self._event(conn, "executed", "Paper purchase completed", f"{trade['quantity']} {trade['symbol'].removesuffix('USDT')} · {trade['total']} USDT including fees")
            return {"trade": trade, "already_executed": False}
