from backend.market import PAIRS


def exchange_info(step="0.00000001", minimum="5", mins=0):
    return {"exchangeFilters": [], "symbols": [
        {"symbol": symbol, "baseAsset": symbol.removesuffix("USDT"), "quoteAsset": "USDT",
         "status": "TRADING", "isSpotTradingAllowed": True, "orderTypes": ["MARKET"],
         "filters": [{"filterType": "LOT_SIZE", "minQty": step, "maxQty": "1000000000", "stepSize": step},
                     {"filterType": "MARKET_LOT_SIZE", "minQty": "0", "maxQty": "1000000000", "stepSize": "0"},
                     {"filterType": "MIN_NOTIONAL", "minNotional": minimum, "applyToMarket": True, "avgPriceMins": mins}]}
        for symbol in PAIRS]}


def public_response(path, params):
    return exchange_info() if path == "exchangeInfo" else {"mins": 5, "price": "650"}
