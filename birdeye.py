"""
birdeye.py - Holder data using Helius (Birdeye replaced)
Falls back gracefully if Helius unavailable.
"""

import requests
from config import HELIUS_API_KEY, DEBUG_MODE
from rate_limiter import wait_for


def get_token_overview(mint_address):
    """Gets token overview - returns None gracefully if unavailable."""
    return None


def get_top_holders(mint_address, limit=10):
    """Gets top token holders using Helius RPC."""
    if not HELIUS_API_KEY:
        return []

    wait_for("helius")
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

    try:
        response = requests.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint_address]
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        accounts = data.get("result", {}).get("value", [])
        if not accounts:
            return []

        total = sum(float(a.get("uiAmount", 0) or 0) for a in accounts)

        return [
            {
                "address": acc.get("address"),
                "amount": float(acc.get("uiAmount", 0) or 0),
                "percentage": (float(acc.get("uiAmount", 0) or 0) / total) if total > 0 else 0,
            }
            for acc in accounts[:limit]
        ]

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Helius holders error: {e}")
        return []


def get_holder_distribution(mint_address):
    """Calculates holder distribution metrics."""
    holders = get_top_holders(mint_address, limit=20)

    if not holders:
        return None

    top1_pct = holders[0]["percentage"] if holders else 0
    top5_pct = sum(h["percentage"] for h in holders[:5])
    top10_pct = sum(h["percentage"] for h in holders[:10])

    return {
        "top1_percentage": top1_pct,
        "top5_percentage": top5_pct,
        "top10_percentage": top10_pct,
        "holder_count": len(holders),
        "is_concentrated": top1_pct > 0.20 or top10_pct > 0.50,
    }


if __name__ == "__main__":
    print("Testing birdeye.py (Helius-backed)...")
    bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    dist = get_holder_distribution(bonk)
    if dist:
        print(f"  Top 1: {dist['top1_percentage']*100:.1f}%")
        print(f"  Top 10: {dist['top10_percentage']*100:.1f}%")
        print("✅ birdeye.py working!")
    else:
        print("⚠️ No holder data returned")
