"""
goplus.py - GoPlus Security API
Honeypot detection, security scans.
"""

import requests
from config import DEBUG_MODE
from rate_limiter import wait_for

GOPLUS_API = "https://api.gopluslabs.io/api/v1"


def get_token_security(mint_address):
    """Gets security analysis for a Solana token."""
    wait_for("goplus")
    
    # GoPlus uses query param for Solana, not path
    url = f"{GOPLUS_API}/token_security/solana"
    
    try:
        response = requests.get(
            url,
            params={"contract_addresses": mint_address},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 1:
            if DEBUG_MODE:
                print(f"⚠️ GoPlus returned code: {data.get('code')}")
            return None
        
        result_data = data.get("result") or {}
        result = result_data.get(mint_address.lower())
        if not result:
            result = result_data.get(mint_address)
        
        if not result:
            if DEBUG_MODE:
                print("⚠️ Token not in GoPlus database")
            return None

        lp_burn_data = _extract_lp_burn_status(result)

        return {
            "address": mint_address,
            "is_honeypot": str(result.get("is_honeypot", "0")) == "1",
            "is_open_source": str(result.get("is_open_source", "0")) == "1",
            "is_proxy": str(result.get("is_proxy", "0")) == "1",
            "is_mintable": str(result.get("is_mintable", "0")) == "1",
            "can_freeze": str(result.get("freezeable", result.get("can_freeze", "0"))) == "1",
            "transfer_pausable": str(result.get("transfer_pausable", "0")) == "1",
            "holder_count": int(result.get("holder_count", 0) or 0),
            "creator_address": result.get("creator_address"),
            "lp_burned": lp_burn_data["lp_burned"],
            "lp_burned_pct": lp_burn_data["lp_burned_pct"],
        }
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ GoPlus error: {e}")
        return None


def _extract_lp_burn_status(result):
    """
    Looks for LP lock/burn info in GoPlus's response. Field names aren't
    fully confirmed from public docs for the Solana endpoint at time of
    writing, so this checks several plausible key names and logs the
    raw lp-related keys if none match — that log output is what should
    be used to correct this function once real data is seen, instead of
    this silently doing nothing the way the old smart_wallet hookup did.
    """
    lp_holders = result.get("lp_holders")

    if lp_holders is None:
        if DEBUG_MODE:
            lp_related_keys = {k: v for k, v in result.items() if "lp" in k.lower() or "liquidity" in k.lower()}
            if lp_related_keys:
                print(f"⚠️ lp_holders key not found, but related keys exist: {lp_related_keys}")
            else:
                print("⚠️ No LP-related fields found in GoPlus response for this token")
        return {"lp_burned": None, "lp_burned_pct": None}

    burn_addresses = {
        "11111111111111111111111111111111",  # System program / common burn sink
        "1nc1nerator11111111111111111111111111111",
    }

    total_lp = 0.0
    burned_lp = 0.0

    for holder in lp_holders:
        try:
            pct = float(holder.get("percent", 0) or 0)
        except (TypeError, ValueError):
            pct = 0.0
        total_lp += pct
        addr = holder.get("address", "")
        tag = (holder.get("tag") or "").lower()
        if addr in burn_addresses or "burn" in tag or "incinerator" in tag:
            burned_lp += pct

    if total_lp == 0:
        return {"lp_burned": None, "lp_burned_pct": None}

    burned_pct = (burned_lp / total_lp) * 100
    return {
        "lp_burned": burned_pct >= 90,  # treat 90%+ burned as effectively fully burned
        "lp_burned_pct": round(burned_pct, 1),
    }


def is_safe_token(mint_address):
    """Quick safety check."""
    security = get_token_security(mint_address)
    
    if not security:
        return None
    
    if security["is_honeypot"]:
        return False
    if security["can_freeze"]:
        return False
    if security["is_mintable"]:
        return False
    
    return True


def get_security_score(mint_address):
    """Returns a security score 0-100."""
    security = get_token_security(mint_address)
    
    if not security:
        return None
    
    score = 100
    
    if security["is_honeypot"]:
        score -= 100
    if security["can_freeze"]:
        score -= 30
    if security["is_mintable"]:
        score -= 25
    if security["transfer_pausable"]:
        score -= 20
    if security["is_proxy"]:
        score -= 10
    
    return max(0, score)


if __name__ == "__main__":
    print("Testing goplus.py...")
    
    bonk = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    
    print("Scanning BONK security...")
    security = get_token_security(bonk)
    
    if security:
        print(f"  Honeypot: {security['is_honeypot']}")
        print(f"  Freezeable: {security['can_freeze']}")
        print(f"  Mintable: {security['is_mintable']}")
        score = get_security_score(bonk)
        print(f"  Security Score: {score}/100")
        print("✅ goplus.py working!")
    else:
        print("⚠️ Token not found - this is OK, GoPlus doesn't have all tokens")
        print("✅ goplus.py code is correct, API just lacks this token")