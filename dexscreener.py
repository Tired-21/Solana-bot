"""
dexscreener.py - DexScreener API
"""

import requests
import time
from config import DEXSCREENER_API, DEBUG_MODE
from rate_limiter import wait_for


def get_token_data(token_address):
    wait_for("dexscreener")
    url = f"{DEXSCREENER_API}/dex/tokens/{token_address}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("pairs"):
            return None
        
        pairs = data["pairs"]
        solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        
        if not solana_pairs:
            return None
        
        main_pair = max(solana_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0))
        return parse_pair_data(main_pair)
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ DexScreener error: {e}")
        return None


def parse_pair_data(pair):
    try:
        price_change = pair.get("priceChange", {})
        volume = pair.get("volume", {})
        liquidity = pair.get("liquidity", {})
        txns = pair.get("txns", {})
        txns_5m = txns.get("m5", {})
        txns_1h = txns.get("h1", {})
        
        return {
            "address": pair.get("baseToken", {}).get("address"),
            "symbol": pair.get("baseToken", {}).get("symbol"),
            "name": pair.get("baseToken", {}).get("name"),
            "price_usd": float(pair.get("priceUsd", 0) or 0),
            "market_cap_usd": float(pair.get("marketCap", 0) or 0),
            "fdv_usd": float(pair.get("fdv", 0) or 0),
            "liquidity_usd": float(liquidity.get("usd", 0) or 0),
            "volume_5m": float(volume.get("m5", 0) or 0),
            "volume_1h": float(volume.get("h1", 0) or 0),
            "volume_24h": float(volume.get("h24", 0) or 0),
            "price_change_5m": float(price_change.get("m5", 0) or 0) / 100,
            "price_change_1h": float(price_change.get("h1", 0) or 0) / 100,
            "price_change_24h": float(price_change.get("h24", 0) or 0) / 100,
            "buys_5m": int(txns_5m.get("buys", 0) or 0),
            "sells_5m": int(txns_5m.get("sells", 0) or 0),
            "buys_1h": int(txns_1h.get("buys", 0) or 0),
            "sells_1h": int(txns_1h.get("sells", 0) or 0),
            "pair_address": pair.get("pairAddress"),
            "dex_id": pair.get("dexId"),
            "pair_created_at": _validate_created_at(pair.get("pairCreatedAt")),
            "url": pair.get("url"),
        }
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Parse error: {e}")
        return None


def _validate_created_at(raw_value):
    """
    DexScreener's pairCreatedAt is sometimes missing, zero, or points to
    a pool re-index event rather than true launch time. This does a basic
    sanity check and logs when something looks off, instead of silently
    trusting whatever comes back.
    """
    if not raw_value:
        if DEBUG_MODE:
            print("⚠️  pairCreatedAt missing from DexScreener response")
        return None

    ts = raw_value / 1000 if raw_value > 1e12 else raw_value
    now = time.time()

    if ts > now:
        if DEBUG_MODE:
            print(f"⚠️  pairCreatedAt is in the future ({ts}), discarding")
        return None

    if ts < now - (365 * 24 * 3600):
        if DEBUG_MODE:
            print(f"⚠️  pairCreatedAt is over a year old ({ts}), suspicious for a pump.fun token")
        return None

    return raw_value


def search_tokens(query):
    wait_for("dexscreener")
    url = f"{DEXSCREENER_API}/dex/search/?q={query}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        pairs = data.get("pairs", [])
        solana_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        
        return [parse_pair_data(p) for p in solana_pairs if parse_pair_data(p)]
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Search error: {e}")
        return []


if __name__ == "__main__":
    print("Testing dexscreener.py...")
    results = search_tokens("bonk")
    
    if results:
        token = results[0]
        print(f"Found: {token['symbol']}")
        print(f"  Price: ${token['price_usd']}")
        print(f"  MC: ${token['market_cap_usd']:,.0f}")
        print(f"  Liquidity: ${token['liquidity_usd']:,.0f}")
        print("✅ dexscreener.py working!")
    else:
        print("No results - try again")