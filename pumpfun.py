"""
pumpfun.py - Pump.fun data via DexScreener latest endpoint
"""

import time
import requests
from config import DEBUG_MODE
from rate_limiter import wait_for

DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex"
DEXSCREENER_LATEST = "https://api.dexscreener.com/token-profiles/latest/v1"


def get_new_tokens(limit=50):
    """Get newest Pump.fun tokens via DexScreener latest endpoint."""
    try:
        # This hits the strict 60/min token-profiles endpoint — was
        # previously firing with zero rate limiting, the likely main
        # source of the 429 storm seen in testing.
        wait_for("dexscreener_profiles")
        response = requests.get(DEXSCREENER_LATEST, timeout=10)
        response.raise_for_status()
        data = response.json()

        # This endpoint returns a list directly
        profiles = data if isinstance(data, list) else []

        # Filter Solana pump.fun tokens only
        solana_profiles = [
            p for p in profiles
            if p.get("chainId") == "solana" and
            "pump" in str(p.get("tokenAddress", "")).lower()
        ]

        if DEBUG_MODE:
            print(f"  Found {len(solana_profiles)} pump.fun profiles from latest endpoint")

        if not solana_profiles:
            return []

        tokens = []
        now = time.time()

        for p in solana_profiles:
            address = p.get("tokenAddress", "")
            if not address or address.startswith("0x"):
                continue

            # Fetch pair data for this token — also unrated before.
            # Pair-data endpoints allow 300/min per DexScreener's docs,
            # much looser than the profile endpoint, so this uses its
            # own separate, faster rate-limit bucket.
            try:
                wait_for("dexscreener_pairs")
                pair_url = f"{DEXSCREENER_BASE}/tokens/{address}"
                pair_resp = requests.get(pair_url, timeout=10)
                pair_resp.raise_for_status()
                pair_data = pair_resp.json()

                pairs = pair_data.get("pairs", [])
                solana_pairs = [x for x in pairs if x.get("chainId") == "solana"]

                if not solana_pairs:
                    continue

                pair = max(solana_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)

                mc = float(pair.get("fdv", 0) or 0)
                liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                created = pair.get("pairCreatedAt")

                if not created:
                    continue

                age_minutes = (now - created / 1000) / 60
                if age_minutes > 20:
                    continue

                if mc > 500000:
                    continue

                tokens.append({
                    "address": address,
                    "symbol": pair.get("baseToken", {}).get("symbol"),
                    "name": pair.get("baseToken", {}).get("name"),
                    "creator": None,
                    "created_timestamp": created,
                    "market_cap": mc,
                    "market_cap_usd": mc,
                    "liquidity_usd": liq,
                    "is_graduated": False,
                    "bonding_curve": pair.get("pairAddress"),
                })

            except Exception as e:
                if DEBUG_MODE:
                    print(f"  ⚠️ Skipping {address}: {e}")
                continue

        if DEBUG_MODE:
            print(f"  {len(tokens)} fresh tokens after filtering")

        return tokens[:limit]

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ get_new_tokens error: {e}")
        return []


def get_token_info(mint_address):
    """Get specific token info via DexScreener."""
    try:
        url = f"{DEXSCREENER_BASE}/tokens/{mint_address}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        pairs = data.get("pairs", [])
        if not pairs:
            return None

        p = pairs[0]
        return {
            "address": mint_address,
            "symbol": p.get("baseToken", {}).get("symbol"),
            "name": p.get("baseToken", {}).get("name"),
            "market_cap": float(p.get("fdv", 0) or 0),
            "market_cap_usd": float(p.get("fdv", 0) or 0),
            "liquidity_usd": float(p.get("liquidity", {}).get("usd", 0) or 0),
            "is_graduated": True,
            "raydium_pool": p.get("pairAddress"),
        }

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ get_token_info error: {e}")
        return None


def get_graduating_tokens():
    """Get tokens near graduation threshold (~$69k-$100k MC)."""
    try:
        url = f"{DEXSCREENER_BASE}/search?q=pump.fun&chainId=solana"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        pairs = data.get("pairs", [])
        graduating = []

        for p in pairs:
            mc = float(p.get("fdv", 0) or 0)
            if 69000 <= mc <= 105000:
                graduating.append({
                    "address": p.get("baseToken", {}).get("address"),
                    "symbol": p.get("baseToken", {}).get("symbol"),
                    "market_cap": mc,
                })

        return graduating

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ get_graduating_tokens error: {e}")
        return []


if __name__ == "__main__":
    print("Testing pumpfun.py...")

    print("\n1. Testing get_new_tokens...")
    tokens = get_new_tokens(limit=5)
    if tokens:
        print(f"✅ Found {len(tokens)} fresh tokens:")
        for t in tokens[:3]:
            print(f"   {t['symbol']}: ${t['market_cap']:,.0f} MC | liq=${t['liquidity_usd']:,.0f}")
    else:
        print("⚠️ No fresh tokens right now")

    print("\n2. Testing get_graduating_tokens...")
    graduating = get_graduating_tokens()
    if graduating:
        print(f"✅ Found {len(graduating)} near-graduation tokens:")
        for t in graduating[:3]:
            print(f"   {t['symbol']}: ${t['market_cap']:,.0f} MC")
    else:
        print("⚠️ No tokens near graduation right now (normal)")

    print("\n3. Testing get_token_info...")
    if tokens and tokens[0]["address"]:
        info = get_token_info(tokens[0]["address"])
        if info:
            print(f"✅ Token info: {info['symbol']} - ${info['market_cap']:,.0f} MC")
        else:
            print("❌ get_token_info failed")

    print("\n[Done]")