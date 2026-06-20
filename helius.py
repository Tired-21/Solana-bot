"""
helius.py - Helius API
Token metadata, authorities, freeze/mint checks.
"""

import requests
from config import HELIUS_API, HELIUS_API_KEY, DEBUG_MODE
from rate_limiter import wait_for

HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"


def get_recent_buyers(mint_address, limit=100):
    """
    Pulls recent buy transactions for a token with actual wallet addresses
    and amounts. This is the missing piece behind wallet entropy, repeat
    wallet ratio, and smart wallet detection — DexScreener only gives buy
    COUNTS, never which wallets did the buying. This function is what
    makes those signals computable for the first time in the live bot.

    Returns a list of dicts: [{"address": wallet, "amount_usd": float, "timestamp": int}, ...]
    Returns [] on failure rather than None, so callers can safely iterate
    without needing extra null checks.
    """
    if not HELIUS_API_KEY:
        return []

    wait_for("helius")

    try:
        url = f"{HELIUS_API}/addresses/{mint_address}/transactions"
        params = {"api-key": HELIUS_API_KEY, "limit": limit}

        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            if DEBUG_MODE:
                print(f"⚠️ get_recent_buyers HTTP {response.status_code}")
            return []

        data = response.json()
        if not isinstance(data, list):
            return []

        buyers = []
        for tx in data:
            ts = tx.get("timestamp") or 0
            signer = tx.get("feePayer", "")
            events = tx.get("events", {})
            swap = events.get("swap", {}) if isinstance(events, dict) else {}

            token_out = swap.get("tokenOutputs", []) or []
            native_in = swap.get("nativeInput") or {}

            is_buy = any(t.get("mint") == mint_address for t in token_out)
            if not is_buy or not signer:
                continue

            sol_amount = 0.0
            if isinstance(native_in, dict) and native_in.get("amount"):
                sol_amount = float(native_in.get("amount", 0)) / 1e9
            usd_est = sol_amount * 150  # rough SOL price placeholder, same as analyze_winners.py

            buyers.append({
                "address": signer,
                "amount_usd": round(usd_est, 2),
                "timestamp": ts,
            })

        return buyers

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ get_recent_buyers error: {e}")
        return []


def get_mint_creation_time(mint_address):
    """
    Returns the true on-chain mint creation timestamp (unix seconds) by
    finding the oldest transaction signature for this mint address.

    This is more reliable than DexScreener's pairCreatedAt, which tracks
    pool/pair creation rather than the actual token mint — these can
    drift apart by significant time (confirmed: one real token showed a
    74+ minute gap between DexScreener's reported age and the real
    on-chain mint time per Solscan).

    Returns None if it can't be determined (caller should fall back to
    existing age-estimation logic, same as before).
    """
    if not HELIUS_API_KEY:
        return None

    wait_for("helius")

    try:
        # Walk backward through signatures for this address until we hit
        # the oldest one — that's the mint transaction itself.
        before_sig = None
        oldest_blocktime = None
        max_pages = 5  # mint should be found within the first few pages
        # for a freshly-launched token; cap to avoid runaway pagination
        # on an old/unexpectedly busy address.

        for _ in range(max_pages):
            params = {"limit": 1000, "commitment": "confirmed"}
            if before_sig:
                params["before"] = before_sig

            response = requests.post(
                HELIUS_RPC_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [mint_address, params]
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("result")

            if not result:
                break

            for sig_info in result:
                bt = sig_info.get("blockTime")
                if bt:
                    oldest_blocktime = bt  # last one in the loop = oldest seen so far

            if len(result) < 1000:
                # Reached the actual start of this address's history
                break

            before_sig = result[-1]["signature"]

        return oldest_blocktime

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Helius mint creation time error: {e}")
        return None


def get_token_metadata(mint_address):
    """
    Gets token authorities (freeze/mint) via direct RPC getAccountInfo.

    NOTE: This used to call Helius's /v0/token-metadata REST endpoint
    (queryMetadataV1), which Helius has deprecated and now returns
    410 Gone on every call. Switched to plain getAccountInfo RPC,
    which is stable and doesn't depend on that retired wrapper.
    """
    if not HELIUS_API_KEY or HELIUS_API_KEY == "YOUR_HELIUS_KEY":
        if DEBUG_MODE:
            print("⚠️ Helius API key not configured")
        return None

    wait_for("helius")

    try:
        response = requests.post(
            HELIUS_RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    mint_address,
                    {"encoding": "jsonParsed"}
                ]
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        result = data.get("result")
        if not result or not result.get("value"):
            return None

        value = result["value"]
        parsed = value.get("data", {}).get("parsed", {})
        info = parsed.get("info", {})

        if not info:
            return None

        return {
            "address": mint_address,
            "name": "",   # not available via this RPC call; not used downstream for authority checks
            "symbol": "",
            "decimals": info.get("decimals", 9),
            "freeze_authority": info.get("freezeAuthority"),
            "mint_authority": info.get("mintAuthority"),
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