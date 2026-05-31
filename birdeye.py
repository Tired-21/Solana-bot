"""
birdeye.py - Holder data via Helius RPC (Birdeye replaced)
"""

import requests
from config import HELIUS_API_KEY, DEBUG_MODE
from rate_limiter import wait_for


def get_token_overview(mint_address):
    return None


def get_top_holders(mint_address, limit=10):
    if not HELIUS_API_KEY:
        return []
    wait_for("helius")
    url = "https://mainnet.helius-rpc.com/?api-key=" + HELIUS_API_KEY
    try:
        response = requests.post(url, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint_address]
        }, timeout=10)
        response.raise_for_status()
        data = response.json()
        accounts = data.get("result", {}).get("value", [])
        if not accounts:
            return []
        total = sum(float(a.get("uiAmount") or 0) for a in accounts)
        if total == 0:
            return []
        return [
            {
                "address": a.get("address"),
                "amount": float(a.get("uiAmount") or 0),
                "percentage": float(a.get("uiAmount") or 0) / total,
            }
            for a in accounts[:limit]
        ]
    except Exception as e:
        if DEBUG_MODE:
            print("Helius holders error: " + str(e))
        return []


def get_holder_distribution(mint_address):
    holders = get_top_holders(mint_address, limit=20)
    if not holders:
        return None
    top1 = holders[0]["percentage"] if holders else 0
    top5 = sum(h["percentage"] for h in holders[:5])
    top10 = sum(h["percentage"] for h in holders[:10])
    return {
        "top1_percentage": top1,
        "top5_percentage": top5,
        "top10_percentage": top10,
        "holder_count": len(holders),
        "is_concentrated": top1 > 0.20 or top10 > 0.50,
    }
