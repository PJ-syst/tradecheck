"""Exchange metadata checks for an immediate paper MARKET buy.

These checks model quantities and notionals, not an executable exchange offer.
Account counters refer to the paper wallet, which has no open orders.
"""

from decimal import Decimal, InvalidOperation, ROUND_DOWN
from math import lcm

from backend.market import MarketUnavailable, PAIRS


def decimal_value(value):
    if not isinstance(value, str) or len(value) > 40:
        raise MarketUnavailable("Invalid exchange numeric field.")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise MarketUnavailable("Invalid exchange numeric field.") from None
    if not result.is_finite() or result < 0 or result > Decimal("1e18") or result.as_tuple().exponent < -18:
        raise MarketUnavailable("Invalid exchange numeric field.")
    return result


NUMERIC_FIELDS = {
    "LOT_SIZE": ("minQty", "maxQty", "stepSize"),
    "MARKET_LOT_SIZE": ("minQty", "maxQty", "stepSize"),
    "MIN_NOTIONAL": ("minNotional",),
    "NOTIONAL": ("minNotional", "maxNotional"),
    "MAX_POSITION": ("maxPosition",),
}
COUNTERS = {"MAX_NUM_ORDERS": "maxNumOrders", "MAX_NUM_ALGO_ORDERS": "maxNumAlgoOrders",
            "MAX_NUM_ICEBERG_ORDERS": "maxNumIcebergOrders", "MAX_NUM_ORDER_LISTS": "maxNumOrderLists",
            "EXCHANGE_MAX_NUM_ORDERS": "maxNumOrders", "EXCHANGE_MAX_NUM_ALGO_ORDERS": "maxNumAlgoOrders",
            "EXCHANGE_MAX_NUM_ICEBERG_ORDERS": "maxNumIcebergOrders", "EXCHANGE_MAX_NUM_ORDER_LISTS": "maxNumOrderLists"}
NOT_APPLICABLE = {"PRICE_FILTER", "PERCENT_PRICE", "PERCENT_PRICE_BY_SIDE", "ICEBERG_PARTS",
                  "TRAILING_DELTA", "MAX_NUM_ORDER_AMENDS"}


def validate_filters(rows):
    if not isinstance(rows, list) or len(rows) > 50:
        raise MarketUnavailable("Invalid exchange filters.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("filterType"), str) or row["filterType"] in seen:
            raise MarketUnavailable("Invalid or duplicate exchange filter.")
        kind = row["filterType"]
        seen.add(kind)
        for field in NUMERIC_FIELDS.get(kind, ()):
            decimal_value(row.get(field))
        if kind in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
            if Decimal(row["maxQty"]) and Decimal(row["minQty"]) > Decimal(row["maxQty"]):
                raise MarketUnavailable("Invalid quantity range.")
        if kind == "LOT_SIZE" and (Decimal(row["stepSize"]) == 0 or Decimal(row["maxQty"]) == 0):
            raise MarketUnavailable("Invalid lot size.")
        if kind in {"MIN_NOTIONAL", "NOTIONAL"}:
            flags = ("applyToMarket",) if kind == "MIN_NOTIONAL" else ("applyMinToMarket", "applyMaxToMarket")
            if any(type(row.get(flag)) is not bool for flag in flags) or type(row.get("avgPriceMins")) is not int or not 0 <= row["avgPriceMins"] <= 1440:
                raise MarketUnavailable("Invalid notional configuration.")
        if kind in COUNTERS and (type(row.get(COUNTERS[kind])) is not int or row[COUNTERS[kind]] < 0):
            raise MarketUnavailable("Invalid order counter.")
    return rows


def exchange_symbols(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise MarketUnavailable("Invalid exchange information.")
    exchange = validate_filters(payload.get("exchangeFilters", []))
    result = {}
    for row in payload["symbols"]:
        if not isinstance(row, dict) or row.get("symbol") not in PAIRS or row["symbol"] in result:
            raise MarketUnavailable("Invalid exchange symbol.")
        symbol = row["symbol"]
        if row.get("baseAsset") != symbol.removesuffix("USDT") or row.get("quoteAsset") != "USDT":
            raise MarketUnavailable("Unexpected exchange asset pair.")
        if not isinstance(row.get("status"), str) or type(row.get("isSpotTradingAllowed")) is not bool or not isinstance(row.get("orderTypes"), list):
            raise MarketUnavailable("Missing exchange trading permissions.")
        filters = validate_filters(row.get("filters"))
        if not any(item["filterType"] == "LOT_SIZE" for item in filters):
            raise MarketUnavailable("Exchange quantity rules are missing.")
        result[symbol] = {"status": row["status"], "spot": row["isSpotTradingAllowed"],
                          "market": "MARKET" in row["orderTypes"], "filters": filters, "exchange_filters": exchange}
    if set(result) != set(PAIRS):
        raise MarketUnavailable("Exchange information is incomplete.")
    return result


def estimate(amount, price, metadata, holding=Decimal(0)):
    filters = metadata["filters"] + metadata["exchange_filters"]
    steps = [decimal_value(row["stepSize"]) for row in filters
             if row["filterType"] in {"LOT_SIZE", "MARKET_LOT_SIZE"} and Decimal(row["stepSize"]) > 0]
    scale = max([-step.as_tuple().exponent for step in steps] + [8])
    unit = Decimal(10) ** -scale
    step = Decimal(lcm(*(int(value / unit) for value in steps))) * unit if steps else unit
    quantity = (amount / price / step).to_integral_value(rounding=ROUND_DOWN) * step
    checks = [{"name": "Exchange market status", "pass": metadata["status"] == "TRADING" and metadata["spot"] and metadata["market"],
               "detail": "Symbol must allow Spot MARKET orders and have TRADING status."},
              {"name": "Rounded quantity", "pass": quantity > 0,
               "detail": f"{quantity} units after rounding down to a {step} increment."}]
    for row in filters:
        kind = row["filterType"]
        passed, detail = True, "Not used by an immediate paper MARKET buy."
        if kind in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
            lower, upper = Decimal(row["minQty"]), Decimal(row["maxQty"])
            passed = quantity >= lower and (upper == 0 or quantity <= upper)
            detail = f"{quantity} units; minimum {lower}, maximum {upper} (0 means disabled for market bounds)."
        elif kind in {"MIN_NOTIONAL", "NOTIONAL"}:
            minimum = row.get("applyToMarket", row.get("applyMinToMarket", False))
            maximum = row.get("applyMaxToMarket", False)
            ref = price if row["avgPriceMins"] == 0 else Decimal(metadata["average"]["price"])
            if (minimum or maximum) and row["avgPriceMins"] and metadata["average"]["mins"] != row["avgPriceMins"]:
                raise MarketUnavailable("Binance average-price window does not match the notional filter.")
            notional = quantity * ref
            passed = (not minimum or notional >= Decimal(row["minNotional"])) and (not maximum or notional <= Decimal(row["maxNotional"]))
            detail = f"Estimated notional {notional} USDT using a {row['avgPriceMins']}-minute reference. Exchange execution may differ."
        elif kind == "MAX_POSITION":
            passed = holding + quantity <= Decimal(row["maxPosition"])
            detail = f"Paper position after purchase: {holding + quantity}; maximum {row['maxPosition']}."
        elif kind in COUNTERS:
            if kind in {"MAX_NUM_ORDERS", "EXCHANGE_MAX_NUM_ORDERS"}:
                passed = row[COUNTERS[kind]] >= 1
                detail = "One immediate paper order; no resting paper orders."
        elif kind not in NOT_APPLICABLE:
            passed, detail = False, "This filter is not supported yet; paper purchase blocked."
        checks.append({"name": kind, "pass": passed, "detail": detail})
    return quantity, checks
