"""Portfolio ledger, accounting, snapshots, and valuation.

Paper and real portfolios are kept distinct by stable portfolio IDs.
Only signed ledger entries are authoritative for holdings; the legacy wallet
row remains the cash authority for the default paper portfolio.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Dict, List, Optional, Any

from backend.market import PAIRS, MarketUnavailable
from backend.filters import decimal_value as _validate_decimal


class AccountingError(ValueError):
    pass


DEFAULT_PORTFOLIO_ID = "paper"
PRECISION = Decimal("0.00000001")
CENT = Decimal("0.01")


def _money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AccountingError("Invalid decimal amount.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise AccountingError("Invalid decimal amount.") from None
    if not number.is_finite() or number < 0 or number > 1_000_000_000:
        raise AccountingError("Amount out of range.")
    return number


def _qty(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise AccountingError("Invalid quantity.")
    try:
        number = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except InvalidOperation:
        raise AccountingError("Invalid quantity.") from None
    if not number.is_finite() or number < 0 or number > 1_000_000_000:
        raise AccountingError("Quantity out of range.")
    return number.quantize(PRECISION)


def _fmt(value):
    return str(value.quantize(CENT))


def _fmt_qty(value):
    quantized = value.quantize(PRECISION)
    return "0" if quantized == 0 else str(quantized.normalize())


def _symbol_to_asset(symbol):
    return symbol.removesuffix("USDT") if symbol.endswith("USDT") else symbol


@dataclass(frozen=True)
class Entry:
    id: str
    portfolio_id: str
    entry_type: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    purchase_cost: Decimal
    fee: Decimal
    net_quote: Decimal
    timestamp: float
    day: str
    source_id: Optional[str]

    def to_row(self):
        return {
            "id": self.id,
            "portfolio_id": self.portfolio_id,
            "entry_type": self.entry_type,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "purchase_cost": str(self.purchase_cost),
            "fee": str(self.fee),
            "net_quote": str(self.net_quote),
            "timestamp": self.timestamp,
            "day": self.day,
            "source_id": self.source_id,
        }

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            portfolio_id=row["portfolio_id"],
            entry_type=row["entry_type"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=Decimal(row["quantity"]),
            price=Decimal(row["price"]),
            purchase_cost=Decimal(row["purchase_cost"]),
            fee=Decimal(row["fee"]),
            net_quote=Decimal(row["net_quote"]),
            timestamp=row["timestamp"],
            day=row["day"],
            source_id=row["source_id"],
        )


class PortfolioStore:
    def __init__(self, connection_factory, clock=None):
        self.connection_factory = connection_factory
        self.clock = clock
        self._ensure_schema()
        self._ensure_default_portfolio()

    def _ensure_schema(self):
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    purchase_cost TEXT NOT NULL,
                    fee TEXT NOT NULL,
                    net_quote TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    day TEXT NOT NULL,
                    source_id TEXT,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ledger_portfolio ON ledger_entries(portfolio_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_symbol ON ledger_entries(portfolio_id, symbol);
                CREATE INDEX IF NOT EXISTS idx_ledger_day ON ledger_entries(day);
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    snapshot_at REAL NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_portfolio ON portfolio_snapshots(portfolio_id, snapshot_at);
            """)

    def _ensure_default_portfolio(self):
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO portfolios VALUES (?, ?, ?, ?)",
                (DEFAULT_PORTFOLIO_ID, "paper", self._now(),
                 json.dumps({"source": "paper wallet", "note": "Default local simulation portfolio"})),
            )

    def _now(self):
        return self.clock() if self.clock else 0.0

    @contextmanager
    def connection(self):
        conn = self.connection_factory()
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add_portfolio(self, portfolio_id, source_type, data=None):
        if not isinstance(portfolio_id, str) or len(portfolio_id) > 64:
            raise AccountingError("Invalid portfolio ID.")
        if source_type not in {"paper", "binance", "manual"}:
            raise AccountingError("Invalid portfolio source type.")
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO portfolios VALUES (?, ?, ?, ?)",
                (portfolio_id, source_type, self._now(), json.dumps(data or {})),
            )

    def record_trade(self, conn, portfolio_id, side, symbol, quantity, price,
                     purchase_cost, fee, net_quote, day, timestamp=None, source_id=None, data=None):
        if side not in {"BUY", "SELL"}:
            raise AccountingError("Side must be BUY or SELL.")
        entry_id = "ledger-" + str(uuid.uuid4())[:12]
        ts = timestamp if timestamp is not None else self._now()
        entry = Entry(
            id=entry_id,
            portfolio_id=portfolio_id,
            entry_type="trade",
            symbol=symbol,
            side=side,
            quantity=quantity if side == "BUY" else -quantity,
            price=price,
            purchase_cost=purchase_cost,
            fee=fee,
            net_quote=net_quote if side == "BUY" else -net_quote,
            timestamp=ts,
            day=day,
            source_id=source_id,
        )
        payload = {**(data or {}), **entry.to_row()}
        conn.execute(
            "INSERT INTO ledger_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (entry.id, entry.portfolio_id, entry.entry_type, entry.symbol,
             entry.side, str(entry.quantity), str(entry.price),
             str(entry.purchase_cost), str(entry.fee), str(entry.net_quote),
             entry.timestamp, entry.day, entry.source_id,
             json.dumps(payload)),
        )
        return entry

    def entries(self, portfolio_id):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM ledger_entries WHERE portfolio_id=? ORDER BY rowid",
                (portfolio_id,),
            ).fetchall()
            return [Entry.from_row(json.loads(row[0])) for row in rows]

    def holdings(self, portfolio_id, conn=None):
        quantities = {}
        basis = {}
        realized_pnl = Decimal("0")
        for entry in self._entries_for_portfolio(portfolio_id, conn):
            asset = _symbol_to_asset(entry.symbol)
            if entry.side == "BUY":
                quantities[asset] = quantities.get(asset, Decimal("0")) + entry.quantity
                basis[asset] = basis.get(asset, Decimal("0")) + entry.purchase_cost + entry.fee
            else:
                disposed_qty = -entry.quantity
                old_qty = quantities.get(asset, Decimal("0"))
                old_basis = basis.get(asset, Decimal("0"))
                if old_qty > 0:
                    disposed_basis = (old_basis / old_qty) * disposed_qty
                    disposed_basis = min(disposed_basis, old_basis)
                else:
                    disposed_basis = Decimal("0")
                quantities[asset] = max(Decimal("0"), old_qty - disposed_qty)
                basis[asset] = max(Decimal("0"), old_basis - disposed_basis)
                gross = disposed_qty * entry.price
                realized_pnl += -entry.net_quote - disposed_basis
        return {"quantities": quantities, "basis": basis, "realized_pnl": realized_pnl}

    def _entries_for_portfolio(self, portfolio_id, conn=None):
        close_conn = False
        if conn is None:
            conn = self.connection_factory()
            close_conn = True
        try:
            rows = conn.execute(
                "SELECT data FROM ledger_entries WHERE portfolio_id=? ORDER BY rowid",
                (portfolio_id,),
            ).fetchall()
        finally:
            if close_conn:
                conn.close()
        return [Entry.from_row(json.loads(row[0])) for row in rows]

    def position(self, portfolio_id, symbol, conn=None):
        state = self.holdings(portfolio_id, conn)
        asset = _symbol_to_asset(symbol)
        return {
            "quantity": state["quantities"].get(asset, Decimal("0")),
            "basis": state["basis"].get(asset, Decimal("0")),
        }

    def holdings_at(self, portfolio_id, ts, conn=None):
        entries = [e for e in self._entries_for_portfolio(portfolio_id, conn) if e.timestamp < ts]
        quantities, basis, realized_pnl = {}, {}, Decimal("0")
        for entry in entries:
            asset = _symbol_to_asset(entry.symbol)
            if entry.side == "BUY":
                quantities[asset] = quantities.get(asset, Decimal("0")) + entry.quantity
                basis[asset] = basis.get(asset, Decimal("0")) + entry.purchase_cost + entry.fee
            else:
                disposed_qty = -entry.quantity
                old_qty = quantities.get(asset, Decimal("0"))
                old_basis = basis.get(asset, Decimal("0"))
                disposed_basis = (old_basis / old_qty) * disposed_qty if old_qty > 0 else Decimal("0")
                disposed_basis = min(disposed_basis, old_basis)
                quantities[asset] = max(Decimal("0"), old_qty - disposed_qty)
                basis[asset] = max(Decimal("0"), old_basis - disposed_basis)
                gross = disposed_qty * entry.price
                realized_pnl += -entry.net_quote - disposed_basis
        return {"quantities": quantities, "basis": basis, "realized_pnl": realized_pnl}

    def _initial_cash(self, portfolio_id, current_cash):
        entries = self._entries_for_portfolio(portfolio_id)
        total_net = sum(e.net_quote for e in entries)
        return Decimal(str(current_cash)) + total_net

    def cash_at(self, portfolio_id, ts, current_cash):
        initial = self._initial_cash(portfolio_id, current_cash)
        net_upto = sum(e.net_quote for e in self._entries_for_portfolio(portfolio_id) if e.timestamp < ts)
        return initial - net_upto

    def period_cash_flow(self, portfolio_id, start_ts, end_ts):
        # External cash flows not yet modelled; net (buy-costs minus sale-proceeds) is implicit in cash.
        return Decimal("0")

    def snapshot(self, portfolio_id, cash, prices):
        state = self.holdings(portfolio_id)
        quantities = state["quantities"]
        basis = state["basis"]
        holdings = []
        total_value = cash
        unpriced = []
        for asset, qty in quantities.items():
            symbol = asset + "USDT" if asset + "USDT" in PAIRS else asset
            price = prices.get(symbol)
            value = None
            if price is not None:
                value = qty * Decimal(str(price))
                total_value += value
            else:
                unpriced.append(asset)
            holdings.append({
                "asset": asset,
                "symbol": symbol,
                "quantity": str(qty),
                "basis": str(basis.get(asset, Decimal("0"))),
                "price": str(price) if price is not None else None,
                "value": str(value) if value is not None else None,
            })
        allocation = []
        if total_value > 0:
            for h in holdings:
                if h["value"] is not None:
                    allocation.append({
                        "asset": h["asset"],
                        "allocation_pct": str((Decimal(h["value"]) / total_value * 100).quantize(CENT)),
                    })
        return {
            "portfolio_id": portfolio_id,
            "snapshot_at": self._now(),
            "cash": str(cash),
            "total_value": str(total_value),
            "holdings": holdings,
            "unpriced": unpriced,
            "coverage": "partial" if unpriced else "complete",
            "realized_pnl": str(state["realized_pnl"]),
        }

    def save_snapshot(self, snapshot):
        snap_id = "snap-" + str(uuid.uuid4())[:12]
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?)",
                (snap_id, snapshot["portfolio_id"], snapshot["snapshot_at"], json.dumps(snapshot)),
            )
        return {"id": snap_id, **snapshot}

    def latest_snapshot(self, portfolio_id):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT data FROM portfolio_snapshots WHERE portfolio_id=? ORDER BY snapshot_at DESC LIMIT 1",
                (portfolio_id,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def prices_at(self, portfolio_id, timestamp):
        """Use an observed boundary quote within five minutes, never a future quote."""
        with self.connection() as conn:
            row = conn.execute("SELECT data FROM portfolio_snapshots WHERE portfolio_id=? AND snapshot_at<=? AND snapshot_at>=? ORDER BY snapshot_at DESC LIMIT 1",
                               (portfolio_id, timestamp, timestamp - 300)).fetchone()
        return json.loads(row[0]).get("prices", {}) if row else {}

    def period_trades(self, portfolio_id, start_ts, end_ts):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM ledger_entries WHERE portfolio_id=? AND entry_type='trade' "
                "AND timestamp >= ? AND timestamp < ? ORDER BY rowid",
                (portfolio_id, start_ts, end_ts),
            ).fetchall()
            return [Entry.from_row(json.loads(row[0])) for row in rows]


def validate_sell_quantity(symbol, requested_quantity, available_quantity, constraints=None):
    qty = _qty(requested_quantity)
    if qty <= 0:
        raise AccountingError("Sale quantity must be greater than zero.")
    available = _qty(available_quantity)
    if qty > available:
        raise AccountingError(f"Cannot sell {qty} {_symbol_to_asset(symbol)}; available: {available}.")
    if constraints:
        from backend.filters import estimate
        # estimate expects amount in quote; for sells we check the quantity directly against lot filters
        metadata = constraints
        step = _step_from_filters(metadata)
        if step and ((qty / step) % Decimal("1")) != 0:
            qty = (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
            if qty <= 0:
                raise AccountingError("Sell quantity too small after exchange rounding.")
            if qty > available:
                raise AccountingError("Rounded sell quantity exceeds available holdings.")
    return qty


def _step_from_filters(metadata):
    from backend.filters import decimal_value
    filters = metadata.get("filters", []) + metadata.get("exchange_filters", [])
    steps = [decimal_value(row["stepSize"]) for row in filters
             if row["filterType"] in {"LOT_SIZE", "MARKET_LOT_SIZE"} and Decimal(row["stepSize"]) > 0]
    if not steps:
        return PRECISION
    from math import lcm
    scale = max([-step.as_tuple().exponent for step in steps] + [8])
    unit = Decimal(10) ** -scale
    return Decimal(lcm(*(int(value / unit) for value in steps))) * unit
