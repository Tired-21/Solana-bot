"""
birdeye.py - Birdeye API
Holder distribution and top holders.
"""

import requests
from config import BIRDEYE_API, BIRDEYE_API_KEY, DEBUG_MODE
from rate_limiter import wait_for


HEADERS = {
    "X-API-KEY": BIRDEYE_API_KEY,
    "x-chain": "solana"
}


def get_token_overview(mint_address):
    """Gets token overview including holder count."""
    wait_for("birdeye")
    url = f"{BIRDEYE_API}/defi/token_overview"
    
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params={"address": mint_address},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            return None
        
        info = data.get("data", {})
        
        return {
            "address": mint_address,
            "holder_count": info.get("holder", 0),
            "price": float(info.get("price", 0) or 0),
            "volume_24h": float(info.get("v24hUSD", 0) or 0),
            "price_change_24h": float(info.get("v24hChangePercent", 0) or 0) / 100,
            "liquidity": float(info.get("liquidity", 0) or 0),
            "market_cap": float(info.get("mc", 0) or 0),
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Birdeye overview error: {e}")
        return None


def get_top_holders(mint_address, limit=10):
    """Gets top token holders with percentages."""
    wait_for("birdeye")
    url = f"{BIRDEYE_API}/defi/token_holder"
    
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params={"address": mint_address, "limit": limit},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            return []
        
        holders = data.get("data", {}).get("items", [])
        
        return [
            {
                "address": h.get("owner"),
                "amount": float(h.get("uiAmount", 0) or 0),
                "percentage": float(h.get("percentage", 0) or 0),
            }
            for h in holders
        ]
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Birdeye holders error: {e}")
        return []


def get_holder_distribution(mint_address):
    """Calculates holder distribution metrics."""
    holders = get_top_holders(mint_address, limit=20)
    
    if not holders:
        return None
    
    top1_pct = holders[0]["percentage"] if len(holders) > 0 else 0
    top5_pct = sum(h["percentage"] for h in holders[:5])
    top10_pct = sum(h["percentage"] for h in holders[:10])
    
    return {
        "top1_percentage": top1_pct,
        "top5_percentage": top5_pct,
        "top10_percentage": top10_pct,
        "holder_count": len(holders),
        "is_concentrated": top1_pct > 20 or top10_pct > 50,
    }


if __name__ == "__main__":
    print("Testing birdeye.py...")
    
    bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    print("Getting BONK overview...")
    overview = get_token_overview(bonk)
    
    if overview:
        print(f"  Holders: {overview['holder_count']:,}")
        print(f"  Price: ${overview['price']}")
        print(f"  Liquidity: ${overview['liquidity']:,.0f}")
        print("✅ birdeye.py working!")
    else:
        print("❌ Failed - check API key")