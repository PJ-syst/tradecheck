"""Portfolio period reports: calculations, narrative, rendering, storage.

Reports reconcile to the ledger, disclose partial coverage, and produce safe,
static Markdown/HTML/JSON renderings.
"""

import html
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.portfolio import DEFAULT_PORTFOLIO_ID, PortfolioStore
from backend.market import PAIRS

REPORT_TTL_SECONDS = 86400
CENT = Decimal("0.01")


class ReportError(ValueError):
    pass


def report_timezone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ReportError("Choose a valid IANA report timezone.") from None


@dataclass
class Period:
    report_type: str
    start_ts: float
    end_ts: float
    label: str
    is_complete: bool


def period_bounds(report_type, tz_name="Africa/Kampala", now=None):
    now = now or datetime.now(timezone.utc).timestamp()
    tz = report_timezone(tz_name)
    now_local = datetime.fromtimestamp(now, tz)
    if report_type == "daily":
        # Completed period = previous local day
        start_local = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        label = start_local.strftime("%Y-%m-%d")
        is_complete = True
    elif report_type == "monthly":
        # Completed period = previous local month
        first_this_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_local = first_this_month
        prev_month = first_this_month - timedelta(days=1)
        start_local = prev_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = start_local.strftime("%Y-%m")
        is_complete = True
    else:
        raise ReportError("Unsupported report type. Use daily or monthly.")
    start_ts = start_local.timestamp()
    end_ts = end_local.timestamp()
    return Period(report_type, start_ts, end_ts, label, is_complete)


def current_period(report_type, tz_name="Africa/Kampala", now=None):
    now = now or datetime.now(timezone.utc).timestamp()
    tz = report_timezone(tz_name)
    now_local = datetime.fromtimestamp(now, tz)
    if report_type == "daily":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"{start_local.strftime('%Y-%m-%d')}-mtd"
    elif report_type == "monthly":
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = f"{start_local.strftime('%Y-%m')}-mtd"
    else:
        raise ReportError("Unsupported report type.")
    return Period(report_type, start_local.timestamp(), now, label, False)


def _fmt(value):
    if value is None:
        return "Unavailable"
    if isinstance(value, Decimal):
        return str(value.quantize(CENT))
    return str(Decimal(str(value)).quantize(CENT))


def _value_for(qty, price):
    if price is None or qty is None:
        return None
    return qty * Decimal(str(price))


class ReportService:
    def __init__(self, portfolio_store, clock=None):
        self.portfolio = portfolio_store
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    def generate(self, portfolio_id, report_type, period, current_cash, prices, evidence=None, narrative=None):
        start_ts, end_ts = period.start_ts, period.end_ts
        opening_state = self.portfolio.holdings_at(portfolio_id, start_ts)
        closing_state = self.portfolio.holdings_at(portfolio_id, end_ts)
        opening_cash = self.portfolio.cash_at(portfolio_id, start_ts, current_cash)
        closing_cash = self.portfolio.cash_at(portfolio_id, end_ts, current_cash)
        trades = self.portfolio.period_trades(portfolio_id, start_ts, end_ts)

        # Current quotes cannot establish historical period valuations.
        opening_prices = self.portfolio.prices_at(portfolio_id, start_ts)
        closing_prices = self.portfolio.prices_at(portfolio_id, end_ts) if period.is_complete else prices
        opening_holdings = self._value_holdings(opening_state["quantities"], opening_prices)
        closing_holdings = self._value_holdings(closing_state["quantities"], closing_prices)
        opening_value = opening_cash + sum(h["value"] for h in opening_holdings if h["value"] is not None)
        closing_value = closing_cash + sum(h["value"] for h in closing_holdings if h["value"] is not None)

        opening_unrealized = sum(
            (h["value"] - opening_state["basis"].get(h["asset"], Decimal("0")))
            for h in opening_holdings if h["value"] is not None
        )
        closing_unrealized = sum(
            (h["value"] - closing_state["basis"].get(h["asset"], Decimal("0")))
            for h in closing_holdings if h["value"] is not None
        )
        realized_period = closing_state["realized_pnl"] - opening_state["realized_pnl"]
        unrealized_change = closing_unrealized - opening_unrealized

        buys = [t for t in trades if t.side == "BUY"]
        sells = [t for t in trades if t.side == "SELL"]
        total_buy_cost = sum(t.net_quote for t in buys)
        total_sell_proceeds = -sum(t.net_quote for t in sells)
        fees = sum(t.fee for t in trades)

        unpriced_opening = [h["asset"] for h in opening_holdings if h["value"] is None and h["quantity"] > 0]
        unpriced_closing = [h["asset"] for h in closing_holdings if h["value"] is None and h["quantity"] > 0]
        coverage_notes = []
        if opening_prices or (period.is_complete and closing_prices):
            coverage_notes.append("Historical valuations use observed quotes from at most five minutes before the period boundary.")
        with self.portfolio.connection() as conn:
            created = conn.execute("SELECT created_at FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
        if created and created[0] > start_ts:
            coverage_notes.append("Collection began after the period opened; earlier history is not verified.")
        if unpriced_opening or unpriced_closing:
            coverage_notes.append(f"Missing historical prices for: {sorted(set(unpriced_opening + unpriced_closing))}.")
        if not period.is_complete:
            coverage_notes.append("This is a current-period, as-of report. Period is not complete.")
        if unpriced_opening:
            opening_value = None
        if unpriced_closing:
            closing_value = None
        known_performance = not unpriced_opening and not unpriced_closing and not (created and created[0] > start_ts)
        coverage_notes.append("Factual report from the paper ledger; no AI narrative or tax calculations.")

        calculations = {
            "period_label": period.label,
            "period_start_utc": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "period_end_utc": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "opening_cash": _fmt(opening_cash),
            "closing_cash": _fmt(closing_cash),
            "opening_value": _fmt(opening_value),
            "closing_value": _fmt(closing_value),
            "opening_holdings": [{"asset": h["asset"], "quantity": str(h["quantity"]), "value": _fmt(h["value"]) if h["value"] is not None else None} for h in opening_holdings],
            "closing_holdings": [{"asset": h["asset"], "quantity": str(h["quantity"]), "value": _fmt(h["value"]) if h["value"] is not None else None, "basis": _fmt(closing_state["basis"].get(h["asset"], Decimal("0")))} for h in closing_holdings],
            "buys": len(buys),
            "sells": len(sells),
            "total_buy_cost": _fmt(total_buy_cost),
            "total_sell_proceeds": _fmt(total_sell_proceeds),
            "fees": _fmt(fees),
            "realized_pnl": _fmt(realized_period),
            "unrealized_change": _fmt(unrealized_change if known_performance else None),
            "total_pnl": _fmt(realized_period + unrealized_change if known_performance else None),
            "coverage": "partial" if coverage_notes else "complete",
            "coverage_notes": coverage_notes,
        }
        rendered = render_report(portfolio_id, calculations, evidence or [], narrative)
        return {"calculations": calculations, **rendered}

    def _value_holdings(self, quantities, prices):
        rows = []
        for asset, qty in quantities.items():
            symbol = asset + "USDT" if asset + "USDT" in PAIRS else asset
            price = prices.get(symbol)
            rows.append({"asset": asset, "quantity": qty, "value": _value_for(qty, price)})
        return rows


def render_report(portfolio_id, calculations, evidence, narrative):
    narrative = narrative or ""
    md = _render_markdown(portfolio_id, calculations, evidence, narrative)
    html_text = _render_html(portfolio_id, calculations, evidence, narrative)
    json_text = json.dumps({"portfolio_id": portfolio_id, "calculations": calculations, "evidence": evidence, "narrative": narrative}, indent=2)
    return {"markdown": md, "html": html_text, "json": json_text}


def _render_markdown(portfolio_id, calc, evidence, narrative):
    lines = [
        f"# Portfolio Report: {calc['period_label']}",
        f"**Portfolio:** `{portfolio_id}`  ",
        f"**Period:** {calc['period_start_utc']} → {calc['period_end_utc']}  ",
        f"**Coverage:** {calc['coverage']}  ",
        "",
        "## Summary",
        f"- Opening value: {calc['opening_value']} USDT",
        f"- Closing value: {calc['closing_value']} USDT",
        f"- Cash: {calc['opening_cash']} → {calc['closing_cash']} USDT",
        f"- Buys: {calc['buys']} · Sells: {calc['sells']}",
        f"- Buy cost: {calc['total_buy_cost']} USDT · Sell proceeds: {calc['total_sell_proceeds']} USDT",
        f"- Fees: {calc['fees']} USDT",
        f"- Realized P&L: {calc['realized_pnl']} USDT",
        f"- Unrealized change: {calc['unrealized_change']} USDT",
        f"- Total P&L (approx): {calc['total_pnl']} USDT",
        "",
    ]
    if calc["coverage_notes"]:
        lines.extend(["## Coverage notes", ""] + [f"- {n}" for n in calc["coverage_notes"]] + [""])
    lines.extend(["## Closing holdings", ""])
    for h in calc["closing_holdings"]:
        lines.append(f"- {h['asset']}: {h['quantity']} · value {h['value']} USDT · basis {h['basis']} USDT")
    lines.append("")
    if narrative:
        lines.extend(["## Narrative", "", narrative, ""])
    if evidence:
        lines.extend(["## Evidence", ""])
        for ev in evidence:
            lines.append(f"- {ev.get('type','evidence')} `{ev.get('id')}`")
    return "\n".join(lines)


def _render_html(portfolio_id, calc, evidence, narrative):
    title = html.escape(f"Report {calc['period_label']}")
    rows = []
    for h in calc["closing_holdings"]:
        rows.append(f"<tr><td>{html.escape(h['asset'])}</td><td>{html.escape(str(h['quantity']))}</td><td>{html.escape(str(h['value']))}</td><td>{html.escape(str(h['basis']))}</td></tr>")
    holdings_table = "".join(rows) if rows else "<tr><td colspan=4>No holdings</td></tr>"
    coverage = "".join(f"<li>{html.escape(n)}</li>" for n in calc["coverage_notes"]) if calc["coverage_notes"] else ""
    evidence_list = "".join(f"<li>{html.escape(ev.get('type','evidence'))} <code>{html.escape(ev.get('id',''))}</code></li>" for ev in evidence)
    narrative_html = f"<h2>Narrative</h2><p>{html.escape(narrative)}</p>" if narrative else ""
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<p><strong>Portfolio:</strong> {html.escape(portfolio_id)}<br>
<strong>Period:</strong> {html.escape(calc['period_start_utc'])} → {html.escape(calc['period_end_utc'])}<br>
<strong>Coverage:</strong> {html.escape(calc['coverage'])}</p>
<h2>Summary</h2>
<ul>
<li>Opening value: {html.escape(calc['opening_value'])} USDT</li>
<li>Closing value: {html.escape(calc['closing_value'])} USDT</li>
<li>Cash: {html.escape(calc['opening_cash'])} → {html.escape(calc['closing_cash'])} USDT</li>
<li>Buys: {calc['buys']} · Sells: {calc['sells']}</li>
<li>Buy cost: {html.escape(calc['total_buy_cost'])} USDT · Sell proceeds: {html.escape(calc['total_sell_proceeds'])} USDT</li>
<li>Fees: {html.escape(calc['fees'])} USDT</li>
<li>Realized P&L: {html.escape(calc['realized_pnl'])} USDT</li>
<li>Unrealized change: {html.escape(calc['unrealized_change'])} USDT</li>
<li>Total P&L (approx): {html.escape(calc['total_pnl'])} USDT</li>
</ul>
{'<h2>Coverage notes</h2><ul>' + coverage + '</ul>' if coverage else ''}
<h2>Closing holdings</h2>
<table border="1" cellpadding="4"><tr><th>Asset</th><th>Quantity</th><th>Value</th><th>Basis</th></tr>{holdings_table}</table>
{narrative_html}
{'<h2>Evidence</h2><ul>' + evidence_list + '</ul>' if evidence else ''}
</body>
</html>"""


class ReportStore:
    def __init__(self, connection_factory, clock=None):
        self.connection_factory = connection_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._ensure_schema()

    @contextmanager
    def connection(self):
        conn = self.connection_factory()
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    period_start REAL NOT NULL,
                    period_end REAL NOT NULL,
                    period_label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    generated_at REAL NOT NULL,
                    calculations TEXT NOT NULL,
                    narrative TEXT,
                    markdown TEXT NOT NULL,
                    html TEXT NOT NULL,
                    json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reports_portfolio ON reports(portfolio_id, generated_at DESC);
                CREATE TABLE IF NOT EXISTS report_publications (
                    id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt TEXT,
                    published_at REAL NOT NULL
                );
            """)

    def save(self, portfolio_id, report_type, period, status, calculations, narrative, rendered, publication_key=None):
        now = self.clock()
        report_id = "rpt-" + (str(uuid.uuid5(uuid.NAMESPACE_URL, publication_key)) if publication_key else str(uuid.uuid4()))
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT id FROM reports WHERE id=?", (report_id,)).fetchone()
            if existing:
                return {"id": report_id, "status": "published", "already_published": True}
            revision = conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM reports WHERE portfolio_id=? AND report_type=? AND period_label=?", (portfolio_id, report_type, period.label)).fetchone()[0]
            conn.execute(
                "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (report_id, portfolio_id, report_type, period.start_ts, period.end_ts, period.label,
                 status, revision, now, json.dumps(calculations), narrative or "",
                 rendered["markdown"], rendered["html"], rendered["json"]),
            )
            conn.execute("INSERT INTO report_publications VALUES (?, ?, ?, ?, ?, ?)",
                         (str(uuid.uuid4()), report_id, "private dashboard", "published", report_id, now))
        return {"id": report_id, "portfolio_id": portfolio_id, "report_type": report_type,
                "period_label": period.label, "status": status, "revision": revision, "generated_at": now}

    def list(self, portfolio_id, report_type=None, limit=50):
        with self.connection() as conn:
            sql = "SELECT id, report_type, period_label, status, generated_at FROM reports WHERE portfolio_id=?"
            params = [portfolio_id]
            if report_type:
                sql += " AND report_type=?"
                params.append(report_type)
            sql += " ORDER BY generated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def get(self, report_id, format=None):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise ReportError("Report not found.")
            result = dict(row)
            result["calculations"] = json.loads(result["calculations"])
            if format == "json":
                return result["json"]
            if format == "html":
                return result["html"]
            if format == "markdown":
                return result["markdown"]
            return result
