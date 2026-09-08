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
from backend.portfolio import DEFAULT_PORTFOLIO_ID, PortfolioStore, validate_sell_quantity
from backend.advisor import FixtureAdvisor, OpenAIAdvisor, AdvisoryStore, validate_advisory, AdvisoryError
from backend.market_analysis import MarketAnalyzer, InvalidAnalysisRequest, format_evidence_for_prompt as _format_market_evidence
from backend.news import NewsAggregator, NewsError
from backend.reports import ReportService, ReportStore, ReportError, period_bounds, current_period
from backend.scheduler import Scheduler, SchedulerError

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


def quantity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InvalidRequest("Enter a valid quantity.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise InvalidRequest("Enter a valid quantity.") from None
    if not number.is_finite() or number <= 0 or number > 1_000_000_000:
        raise InvalidRequest("Quantity must be greater than zero.")
    return number


def fmt(value):
    return str(value.quantize(CENT))


def fmt_qty(value):
    from backend.portfolio import PRECISION
    quantized = value.quantize(PRECISION)
    return "0" if quantized == 0 else str(quantized.normalize())


def parse_request(message):
    if not isinstance(message, str) or len(message) > 200:
        raise InvalidRequest("Use a short request, such as: Buy 20 USDT of BNB.")
    match = re.fullmatch(
        r"\s*(?:please\s+)?buy\s+([0-9]+(?:\.[0-9]{1,2})?)\s+USDT\s+(?:of|worth of)\s+(BNB|BTC|ETH)(?:/USDT|USDT)?\s*[.!?]?\s*",
        message, re.IGNORECASE,
    )
    if not match:
        raise InvalidRequest("Try: Buy 20 USDT of BNB. This prototype supports one BNB, BTC, or ETH purchase per request.")
    amount = money(match[1])
    if amount <= 0:
        raise InvalidRequest("Purchase amount must be greater than zero.")
    return match[2].upper() + "USDT", amount


class Engine:
    def __init__(self, database, clock=None, market=None, interpreter=None, account=None, portfolio_id=None,
                 portfolio_store=None, advisor=None, market_analyzer=None, news=None,
                 report_service=None, report_store=None, scheduler=None, research=None):
        self.database = str(database)
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self.market = market or FixtureMarket()
        self.interpreter = interpreter or StrictInterpreter()
        self.account = account or DisconnectedAccount()
        self.portfolio_id = portfolio_id or DEFAULT_PORTFOLIO_ID
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY CHECK(id=1), balance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS previews (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, preview_id TEXT UNIQUE NOT NULL, day TEXT NOT NULL, total TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
            """)
            try:
                conn.execute("ALTER TABLE trades ADD COLUMN side TEXT NOT NULL DEFAULT 'BUY'")
            except sqlite3.OperationalError:
                pass
            conn.execute("INSERT OR IGNORE INTO wallet VALUES (1, '125.00')")
            conn.execute("INSERT OR IGNORE INTO settings VALUES (1, ?)", (json.dumps({
                "daily_limit": "50.00", "reserve": "100.00", "allowed_pairs": list(PAIRS), "version": 1,
            }),))
        self.portfolio = portfolio_store or PortfolioStore(
            lambda: sqlite3.connect(self.database, timeout=10), clock=self.clock)
        self.advisory_store = AdvisoryStore(lambda: sqlite3.connect(self.database, timeout=10), clock=self.clock)
        self.report_store = ReportStore(lambda: sqlite3.connect(self.database, timeout=10), clock=self.clock)
        self.scheduler = scheduler or Scheduler(lambda: sqlite3.connect(self.database, timeout=10), clock=self.clock)
        self.advisor = advisor or FixtureAdvisor()
        self.market_analyzer = market_analyzer or MarketAnalyzer()
        self.news = news or NewsAggregator()
        self.research = research
        self.report_service = report_service or ReportService(self.portfolio, clock=self.clock)
        self._migrate_legacy_trades()

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
        spent = Decimal("0")
        for row in conn.execute("SELECT side, total FROM trades WHERE day=?", (self.day(),)):
            if row["side"] == "BUY":
                spent += Decimal(row["total"])
        return rules, balance, spent

    def _event(self, conn, kind, title, detail):
        conn.execute("INSERT INTO events (data) VALUES (?)", (json.dumps({
            "kind": kind, "title": title, "detail": detail, "timestamp": self.clock(),
        }),))

    def _migrate_legacy_trades(self):
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT count(*) FROM ledger_entries WHERE portfolio_id=?", (self.portfolio_id,)
            ).fetchone()[0]
            if existing:
                return
            rows = conn.execute("SELECT data FROM trades ORDER BY rowid").fetchall()
            for row in rows:
                trade = json.loads(row[0])
                if trade.get("side", "BUY") != "BUY":
                    continue
                self.portfolio.record_trade(
                    conn,
                    portfolio_id=self.portfolio_id,
                    side="BUY",
                    symbol=trade["symbol"],
                    quantity=Decimal(trade["quantity"]),
                    price=Decimal(trade["price"]),
                    purchase_cost=Decimal(trade["purchase_cost"]),
                    fee=Decimal(trade["fee"]),
                    net_quote=Decimal(trade["total"]),
                    day=trade["day"],
                    timestamp=trade["timestamp"],
                    source_id=trade["preview_id"],
                    data=trade,
                )

    def state(self):
        market_error = None
        try:
            markets = self.market.snapshot()
        except MarketUnavailable as exc:
            markets, market_error = [], str(exc)
        with self.connection() as conn:
            rules, balance, spent = self._state(conn)
            trades = [json.loads(row[0]) for row in conn.execute("SELECT data FROM trades ORDER BY rowid DESC")]
            holdings = self.portfolio.holdings(self.portfolio_id, conn)["quantities"]
            return {
                "mode": "paper", "rules": rules, "balance": fmt(balance), "spent_today": fmt(spent),
                "remaining_budget": fmt(max(Decimal(0), Decimal(rules["daily_limit"]) - spent)),
                "day": self.day(),
                "holdings": {asset: fmt_qty(qty) for asset, qty in holdings.items()},
                "trades": trades[:30],
                "markets": markets,
                "market_data": {"provider": self.market.name, "source": self.market.source,
                                "status": "unavailable" if market_error else "ready", "error": market_error},
                "events": [json.loads(row[0]) for row in conn.execute("SELECT data FROM events ORDER BY id DESC LIMIT 30")],
                "supported_pairs": list(PAIRS),
                "account": self.account.snapshot(),
                "portfolio": {"id": self.portfolio_id, "source_type": "paper"},
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

    def _holding(self, conn, symbol):
        pos = self.portfolio.position(self.portfolio_id, symbol, conn)
        return pos["quantity"]

    def _evaluate_buy(self, conn, symbol, amount, quote):
        rules, balance, spent = self._state(conn)
        quantity = (amount / Decimal(quote["price"])).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        exchange_checks = []
        purchase_cost = amount
        holding = self._holding(conn, symbol)
        if "constraints" in quote:
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
            "side": "BUY", "symbol": symbol, "amount": fmt(amount), "fee": fmt(fee), "total": fmt(total),
            "price": quote["price"], "quantity": fmt_qty(quantity), "purchase_cost": fmt(purchase_cost),
            "unspent_amount": fmt(amount - purchase_cost), "filter_source": "Binance exchangeInfo" if exchange_checks else "demo minimum",
            "balance_before": fmt(balance), "balance_after": fmt(balance - total),
            "checks": checks, "allowed": passed, "maximum": fmt(maximum) if can_suggest else "0.00",
            "rules_version": rules["version"], "day": self.day(), "price_source": quote["source"], "mode": "paper",
            "quote": quote,
        }

    def _evaluate_sell(self, conn, symbol, requested_quantity, quote):
        from backend.portfolio import AccountingError
        rules, balance, spent = self._state(conn)
        available = self._holding(conn, symbol)
        constraints = quote.get("constraints")
        try:
            quantity = validate_sell_quantity(symbol, requested_quantity, available, constraints)
        except AccountingError as exc:
            return {
                "side": "SELL", "symbol": symbol, "quantity": fmt_qty(Decimal(str(requested_quantity)) if isinstance(requested_quantity, (str, int, float, Decimal)) else Decimal("0")),
                "gross_proceeds": "0.00", "fee": "0.00", "net_proceeds": "0.00",
                "total": "0.00", "price": quote["price"], "balance_before": fmt(balance),
                "balance_after": fmt(balance), "available_before": fmt_qty(available),
                "remaining_quantity": fmt_qty(available),
                "disposed_basis": "0.00",
                "checks": [
                    {"name": "Allowed market", "pass": symbol in rules["allowed_pairs"], "detail": f"{symbol.removesuffix('USDT')}/USDT must be enabled in your rules."},
                    {"name": "Available holdings", "pass": False, "detail": str(exc)},
                ], "allowed": False,
                "rules_version": rules["version"], "day": self.day(), "price_source": quote["source"], "mode": "paper",
                "quote": quote,
            }
        gross = (quantity * Decimal(quote["price"])).quantize(CENT, rounding=ROUND_DOWN)
        min_notional = Decimal("5")
        if constraints:
            min_notional = self._sell_min_notional(constraints)
        # Rounding can reduce quantity; recompute gross after rounding
        gross = (quantity * Decimal(quote["price"])).quantize(CENT, rounding=ROUND_DOWN)
        fee = (gross * FEE_RATE).quantize(CENT, rounding=ROUND_UP)
        net = gross - fee
        checks = [
            {"name": "Allowed market", "pass": symbol in rules["allowed_pairs"], "detail": f"{symbol.removesuffix('USDT')}/USDT must be enabled in your rules."},
            {"name": "Available holdings", "pass": quantity <= available, "detail": f"Selling {fmt_qty(quantity)} / {fmt_qty(available)} available."},
            {"name": "Minimum notional", "pass": gross >= min_notional, "detail": f"Gross proceeds {fmt(gross)} USDT must be at least {fmt(min_notional)}."},
        ]
        if constraints:
            for kind, passed_filter, detail in self._sell_filter_checks(quantity, gross, constraints):
                checks.append({"name": kind, "pass": passed_filter, "detail": detail})
        checks[0] = {"name": "Supported sale", "pass": symbol in PAIRS,
                     "detail": "Disabled buy markets may still be sold to reduce existing holdings."}
        passed = all(check["pass"] for check in checks)
        return {
            "side": "SELL", "symbol": symbol, "quantity": fmt_qty(quantity),
            "gross_proceeds": fmt(gross), "fee": fmt(fee), "net_proceeds": fmt(net),
            "total": fmt(net), "price": quote["price"], "balance_before": fmt(balance),
            "balance_after": fmt(balance + net), "available_before": fmt_qty(available),
            "remaining_quantity": fmt_qty(available - quantity),
            "disposed_basis": fmt(self._disposed_basis(symbol, quantity, available)),
            "checks": checks, "allowed": passed,
            "rules_version": rules["version"], "day": self.day(), "price_source": quote["source"], "mode": "paper",
            "quote": quote,
        }

    def _sell_min_notional(self, constraints):
        from backend.filters import decimal_value
        min_val = Decimal("5")
        for row in constraints.get("filters", []) + constraints.get("exchange_filters", []):
            if row["filterType"] in {"MIN_NOTIONAL", "NOTIONAL"} and row.get("applyToMarket", row.get("applyMinToMarket", False)):
                min_val = max(min_val, decimal_value(row["minNotional"]))
        return min_val

    def _sell_filter_checks(self, quantity, gross, constraints):
        from backend.filters import decimal_value, COUNTERS, NOT_APPLICABLE
        checks = [("Spot market status", constraints.get("status", "TRADING") == "TRADING", "Spot market must be trading.")]
        for row in constraints.get("filters", []) + constraints.get("exchange_filters", []):
            kind = row["filterType"]
            if kind in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
                lower, upper = decimal_value(row["minQty"]), decimal_value(row["maxQty"])
                ok = quantity >= lower and (upper == 0 or quantity <= upper)
                checks.append((kind, ok, f"{fmt_qty(quantity)} units; min {lower}, max {upper}."))
            elif kind in {"MIN_NOTIONAL", "NOTIONAL"}:
                maximum = decimal_value(row.get("maxNotional", "0"))
                ok = not (row.get("applyMaxToMarket", False) and maximum > 0 and gross > maximum)
                checks.append((kind, ok, f"Gross proceeds {fmt(gross)} USDT."))
            elif kind in COUNTERS:
                checks.append((kind, row[COUNTERS[kind]] >= 1 if kind in {"MAX_NUM_ORDERS", "EXCHANGE_MAX_NUM_ORDERS"} else True,
                               "One immediate paper order; no resting orders."))
            elif kind != "MAX_POSITION" and kind not in NOT_APPLICABLE:
                checks.append((kind, False, "Unsupported exchange filter; sale blocked."))
        return checks

    def _disposed_basis(self, symbol, quantity, available):
        with self.connection() as conn:
            state = self.portfolio.holdings(self.portfolio_id, conn)
        asset = symbol.removesuffix("USDT")
        basis = state["basis"].get(asset, Decimal("0"))
        if available > 0 and quantity <= available:
            return (basis / available) * quantity
        return Decimal("0")

    def preview(self, payload):
        if isinstance(payload, str):
            payload = {"message": payload}
        if not isinstance(payload, dict):
            raise InvalidRequest("Request must be a JSON object.")
        side = str(payload.get("side", "BUY")).upper()
        if side == "BUY":
            return self._preview_buy(payload)
        if side == "SELL":
            return self._preview_sell(payload)
        raise InvalidRequest("Side must be BUY or SELL.")

    def _preview_buy(self, payload):
        message = payload.get("message")
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
            result = self._evaluate_buy(conn, symbol, amount, quote)
            expiry = min(now + PREVIEW_TTL, quote["expires_at"]) if quote["expires_at"] is not None else now + PREVIEW_TTL
            result.update({"id": str(uuid.uuid4()), "created_at": now, "expires_at": expiry})
            conn.execute("INSERT INTO previews VALUES (?, ?)", (result["id"], json.dumps(result)))
            self._event(conn, "passed" if result["allowed"] else "blocked", "Purchase checked" if result["allowed"] else "Purchase blocked", f"Buy {result['amount']} USDT of {result['symbol'].removesuffix('USDT')}")
        return result

    def _preview_sell(self, payload):
        symbol = payload.get("symbol")
        requested = payload.get("quantity")
        if symbol not in PAIRS:
            raise InvalidRequest("Choose a supported symbol.")
        qty = quantity(requested)
        quote = self.market.quote(symbol)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = self.clock()
            if quote["expires_at"] is not None and now >= quote["expires_at"]:
                raise MarketUnavailable("Market quote expired. Check your request again.")
            result = self._evaluate_sell(conn, symbol, qty, quote)
            expiry = min(now + PREVIEW_TTL, quote["expires_at"]) if quote["expires_at"] is not None else now + PREVIEW_TTL
            result.update({"id": str(uuid.uuid4()), "created_at": now, "expires_at": expiry})
            conn.execute("INSERT INTO previews VALUES (?, ?)", (result["id"], json.dumps(result)))
            self._event(conn, "passed" if result["allowed"] else "blocked", "Sale checked" if result["allowed"] else "Sale blocked", f"Sell {result['quantity']} {result['symbol'].removesuffix('USDT')}")
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
                raise InvalidRequest("This preview was blocked. Create a new preview.")
            if self.clock() >= preview["expires_at"] or self.day() != preview["day"]:
                raise InvalidRequest("This preview expired. Check your request again.")
            quote = preview.get("quote") or FixtureMarket().quote(preview["symbol"])
            if quote["provider"] == "binance" and "constraints" not in quote:
                raise InvalidRequest("Preview predates exchange-filter checks. Check your request again.")
            if quote["provider"] != self.market.name:
                raise InvalidRequest("Market data source changed. Check your request again.")
            if quote["expires_at"] is not None and self.clock() >= quote["expires_at"]:
                raise InvalidRequest("Market quote expired. Check your request again.")
            side = preview.get("side", "BUY")
            if side == "BUY":
                current = self._evaluate_buy(conn, preview["symbol"], Decimal(preview["amount"]), quote)
            else:
                current = self._evaluate_sell(conn, preview["symbol"], Decimal(preview["quantity"]), quote)
            if current["rules_version"] != preview["rules_version"] or current["balance_before"] != preview["balance_before"] or not current["allowed"]:
                raise InvalidRequest("Your rules or balance changed. Check your request again before approval.")
            if side == "BUY":
                new_balance = Decimal(current["balance_after"])
                quantity_exec = Decimal(current["quantity"])
                purchase_cost = Decimal(current["purchase_cost"])
                fee = Decimal(current["fee"])
                net_quote = Decimal(current["total"])
            else:
                new_balance = Decimal(current["balance_after"])
                quantity_exec = Decimal(current["quantity"])
                purchase_cost = Decimal(current["gross_proceeds"])
                fee = Decimal(current["fee"])
                net_quote = Decimal(current["net_proceeds"])
            trade = {**current, "id": "paper-" + str(uuid.uuid4())[:12], "preview_id": preview_id, "timestamp": self.clock()}
            conn.execute("UPDATE wallet SET balance=? WHERE id=1", (current["balance_after"],))
            conn.execute("INSERT INTO trades (id, preview_id, day, total, data, side) VALUES (?, ?, ?, ?, ?, ?)",
                         (trade["id"], preview_id, self.day(), current["total"], json.dumps(trade), side))
            self.portfolio.record_trade(
                conn,
                portfolio_id=self.portfolio_id,
                side=side,
                symbol=current["symbol"],
                quantity=quantity_exec,
                price=Decimal(current["price"]),
                purchase_cost=purchase_cost,
                fee=fee,
                net_quote=net_quote,
                day=self.day(),
                timestamp=self.clock(),
                source_id=preview_id,
                data=trade,
            )
            asset = current["symbol"].removesuffix("USDT")
            self._event(conn, "executed", f"Paper {'purchase' if side == 'BUY' else 'sale'} completed",
                        f"{trade['quantity']} {asset} · {trade['total']} USDT including fees")
            return {"trade": trade, "already_executed": False}

    def _current_rules_and_cash(self):
        with self.connection() as conn:
            rules, balance, _ = self._state(conn)
            return rules, balance

    def advise(self, payload):
        if not isinstance(payload, dict):
            raise InvalidRequest("Advisory request must be a JSON object.")
        symbol = payload.get("symbol")
        if symbol not in PAIRS:
            raise InvalidRequest("Choose a supported symbol.")
        horizon = payload.get("horizon", "short")
        if horizon not in {"short", "medium", "long"}:
            raise InvalidRequest("Horizon must be short, medium, or long.")
        question = payload.get("question", "") or ""
        if not isinstance(question, str) or len(question) > 500:
            raise InvalidRequest("Question must be a short string.")
        rules, balance = self._current_rules_and_cash()
        with self.connection() as conn:
            _, _, spent = self._state(conn)
        rules = {**rules, "cash": fmt(balance), "spent_today": fmt(spent)}
        holdings = self.portfolio.holdings(self.portfolio_id)["quantities"]
        evidence = []
        if self.research:
            evidence.append(self.research.evidence(symbol))
        try:
            if not isinstance(self.advisor, FixtureAdvisor):
                market_ev = self.market_analyzer.evidence(symbol, horizon)
                evidence.append(_format_market_evidence(market_ev))
            evidence.append({"type": "quote", "id": f"quote-{symbol}", "price": str(self.market.quote(symbol)["price"])})
        except (MarketUnavailable, InvalidAnalysisRequest) as exc:
            evidence.append({"type": "market_analysis", "id": "market-unavailable", "error": str(exc)})
        try:
            asset = symbol.removesuffix("USDT")
            news = self.news.evidence_for_assets([asset])
            for item in news.get("items", [])[:5]:
                evidence.append({
                    "type": "news", "id": item["id"], "headline": item["headline"],
                    "publisher": item["publisher"], "published_at": item["published_at"],
                    "assets": item["assets"], "summary": item["summary"][:300],
                    "canonical_url": item["canonical_url"], "retrieved_at": item["retrieved_at"],
                })
            if not news.get("items"):
                evidence.append({"type": "news_status", "id": "news-unavailable",
                                 "error": "No relevant news from the last 72 hours is available."})
        except NewsError as exc:
            evidence.append({"type": "news", "id": "news-unavailable", "error": str(exc)})
        evidence_ids = [e["id"] for e in evidence if "id" in e]
        holdings_summary = {a: str(q) for a, q in holdings.items()}
        try:
            raw = self.advisor.advise(self.portfolio_id, symbol, horizon, question, rules, holdings_summary, evidence)
            validate_advisory(raw, evidence_ids)
        except (AdvisoryError, ValueError) as exc:
            raise InvalidRequest(str(exc)) from None
        return self.advisory_store.save(
            portfolio_id=self.portfolio_id, asset=symbol, horizon=horizon,
            model_name=self.advisor.name, evidence_ids=evidence_ids, output=raw, evidence=evidence,
        )

    def advice_preview(self, advisory_id, payload):
        advice = self.get_advisory(advisory_id)
        if advice["portfolio_id"] != self.portfolio_id or self.clock() >= advice["expires_at"]:
            raise InvalidRequest("Advice expired or belongs to a different portfolio. Analyze again.")
        side = advice["output"]["recommendation"]
        if side not in {"BUY", "SELL"}:
            raise InvalidRequest("This assessment has no trade proposal.")
        symbol = advice["asset"]
        if side == "BUY":
            amount = money(payload.get("amount"))
            result = self.preview({"message": f"Buy {amount} USDT of {symbol.removesuffix('USDT')}"})
        else:
            result = self.preview({"side": "SELL", "symbol": symbol, "quantity": payload.get("amount")})
        result["advisory_id"] = advisory_id
        with self.connection() as conn:
            conn.execute("UPDATE previews SET data=? WHERE id=?", (json.dumps(result), result["id"]))
        return result

    def get_advisory(self, advisory_id):
        return self.advisory_store.get(advisory_id)

    def generate_report(self, payload):
        if not isinstance(payload, dict):
            raise InvalidRequest("Report request must be a JSON object.")
        report_type = payload.get("report_type", "daily")
        if report_type not in {"daily", "monthly"}:
            raise InvalidRequest("report_type must be daily or monthly.")
        period_kind = payload.get("period", "completed")
        if period_kind not in {"completed", "current"}:
            raise InvalidRequest("Period must be completed or current.")
        tz = payload.get("timezone", "Africa/Kampala")
        now = self.clock()
        try:
            if period_kind == "current":
                period = current_period(report_type, tz, now)
            else:
                period = period_bounds(report_type, tz, now)
        except ReportError as exc:
            raise InvalidRequest(str(exc)) from None
        try:
            prices = {row["symbol"]: row["price"] for row in self.market.snapshot()}
        except MarketUnavailable as exc:
            raise MarketUnavailable(str(exc)) from exc
        with self.connection() as conn:
            _, current_cash, _ = self._state(conn)
        rendered = self.report_service.generate(
            self.portfolio_id, report_type, period, current_cash, prices,
            evidence=[], narrative="",
        )
        meta = self.report_store.save(
            self.portfolio_id, report_type, period, "complete",
            rendered["calculations"], "", rendered,
        )
        return {"report": meta, "calculations": rendered["calculations"]}

    def list_reports(self, payload=None):
        if payload is None:
            payload = {}
        return self.report_store.list(self.portfolio_id, report_type=payload.get("report_type"), limit=payload.get("limit", 50))

    def get_report(self, report_id, format=None):
        return self.report_store.get(report_id, format=format)

    def upsert_schedule(self, payload):
        if not isinstance(payload, dict):
            raise InvalidRequest("Schedule must be a JSON object.")
        payload.setdefault("portfolio_id", self.portfolio_id)
        if payload.get("portfolio_id") != self.portfolio_id:
            raise InvalidRequest("Mismatched portfolio in schedule.")
        try:
            return self.scheduler.upsert(payload)
        except SchedulerError as exc:
            raise InvalidRequest(str(exc)) from None

    def list_schedules(self):
        return self.scheduler.list(portfolio_id=self.portfolio_id)

    def pause_schedule(self, schedule_id):
        self.scheduler.pause(schedule_id)

    def enable_schedule(self, schedule_id):
        self.scheduler.enable(schedule_id)

    def run_due_schedules(self):
        def runner(schedule, period):
            prices = {row["symbol"]: row["price"] for row in self.market.snapshot()}
            with self.connection() as conn:
                _, current_cash, _ = self._state(conn)
            rendered = self.report_service.generate(
                schedule["portfolio_id"], schedule["report_type"], period,
                current_cash, prices, evidence=[], narrative="",
            )
            return self.report_store.save(
                schedule["portfolio_id"], schedule["report_type"], period,
                "complete", rendered["calculations"], "", rendered,
                publication_key=f"{schedule['id']}:{schedule['report_type']}:{period.label}",
            )
        return self.scheduler.tick(runner)

    def capture_snapshot(self):
        rows = self.market.snapshot()
        prices = {row["symbol"]: row["price"] for row in rows}
        _, cash = self._current_rules_and_cash()
        snapshot = self.portfolio.snapshot(self.portfolio_id, cash, prices)
        snapshot.update({"prices": prices, "source": self.market.source})
        return self.portfolio.save_snapshot(snapshot)
