"""
jupiter.py - SOL price via DexScreener (Jupiter API deprecated)
"""

import requests
from config import DEXSCREENER_API, DEBUG_MODE
from rate_limiter import wait_for

SOL_MINT = "So11111111111111111111111111111111111111112"


def get_sol_price():
    """Get SOL price directly from DexScreener."""
    wait_for("dexscreener")
    url = f"{DEXSCREENER_API}/dex/tokens/{SOL_MINT}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        pairs = data.get("pairs", [])
        if not pairs:
            return None

        # Find a USDC or USDT pair for accurate USD price
        for pair in pairs:
            quote = pair.get("quoteToken", {}).get("symbol", "")
            if quote in ("USDC", "USDT"):
                price = pair.get("priceUsd")
                if price:
                    if DEBUG_MODE:
                        print(f"✅ SOL price: ${float(price):.2f}")
                    return float(price)

        # Fallback to first pair if no USDC/USDT found
        price = pairs[0].get("priceUsd")
        if price:
            if DEBUG_MODE:
                print(f"✅ SOL price: ${float(price):.2f}")
            return float(price)

        return None

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Jupiter error: {e}")
        return None


def get_token_price(mint_address):
    """Get token price via DexScreener."""
    wait_for("dexscreener")
    url = f"{DEXSCREENER_API}/dex/tokens/{mint_address}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        pairs = data.get("pairs", [])
        if pairs:
            return float(pairs[0].get("priceUsd", 0) or 0)
        return None

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Token price error: {e}")
        return None


if __name__ == "__main__":
    print("Testing jupiter.py...")
    sol_price = get_sol_price()

    if sol_price:
        print(f"SOL Price: ${sol_price:.2f}")
        print("✅ jupiter.py working!")
    else:
        print("❌ Failed to get SOL price")