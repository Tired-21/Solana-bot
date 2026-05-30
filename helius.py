"""
helius.py - Helius API
Token metadata, authorities, freeze/mint checks.
"""

import requests
from config import HELIUS_API, HELIUS_API_KEY, DEBUG_MODE
from rate_limiter import wait_for


def get_token_metadata(mint_address):
    """Gets token metadata including authorities."""
    if HELIUS_API_KEY == "YOUR_HELIUS_KEY":
        if DEBUG_MODE:
            print("⚠️ Helius API key not configured")
        return None
    
    wait_for("helius")
    url = f"{HELIUS_API}/token-metadata?api-key={HELIUS_API_KEY}"
    
    try:
        response = requests.post(
            url,
            json={"mintAccounts": [mint_address]},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if not data or len(data) == 0:
            return None
        
        token = data[0]
        if not token:
            return None
        
        on_chain = token.get("onChainMetadata") or {}
        account_info = token.get("onChainAccountInfo") or {}
        
        metadata = on_chain.get("metadata") or {}
        meta_data = metadata.get("data") or {}
        
        parsed = account_info.get("accountInfo", {}).get("data", {}).get("parsed", {}).get("info", {})
        
        return {
            "address": mint_address,
            "name": meta_data.get("name", ""),
            "symbol": meta_data.get("symbol", ""),
            "decimals": parsed.get("decimals", 9),
            "freeze_authority": parsed.get("freezeAuthority"),
            "mint_authority": parsed.get("mintAuthority"),
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Helius metadata error: {e}")
        return None


def check_authorities(mint_address):
    """Checks if freeze/mint authorities are enabled (red flags)."""
    metadata = get_token_metadata(mint_address)
    
    if not metadata:
        return {"has_freeze": None, "has_mint": None, "safe": None}
    
    has_freeze = metadata.get("freeze_authority") is not None
    has_mint = metadata.get("mint_authority") is not None
    
    return {
        "has_freeze": has_freeze,
        "has_mint": has_mint,
        "safe": not has_freeze and not has_mint,
        "freeze_authority": metadata.get("freeze_authority"),
        "mint_authority": metadata.get("mint_authority"),
    }


def get_token_holders(mint_address, limit=20):
    """Gets top token holders."""
    if HELIUS_API_KEY == "YOUR_HELIUS_KEY":
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
        
        return [
            {
                "address": acc.get("address"),
                "amount": float(acc.get("amount", 0)),
                "decimals": acc.get("decimals", 9),
            }
            for acc in accounts[:limit]
        ]
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Helius holders error: {e}")
        return []


if __name__ == "__main__":
    print("Testing helius.py...")
    
    bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    print("Checking authorities for BONK...")
    auth = check_authorities(bonk)
    
    print(f"  Freeze authority: {auth['has_freeze']}")
    print(f"  Mint authority: {auth['has_mint']}")
    print(f"  Safe: {auth['safe']}")
    print("✅ helius.py working!")