"""
structural.py - Structural Health Engine
Evaluates safety: holder concentration, authorities, rug indicators.
Weight: 25% of final score
"""

from config import STRUCTURAL_THRESHOLDS, HARD_REJECTS, DEBUG_MODE
from helpers import safe_divide, clamp


def calculate_structural_score(token_address, holder_data, authority_data, security_data):
    """
    Calculates structural health score (0-100).
    Higher = safer token.
    """
    score = 100  # Start at 100, deduct for red flags
    signals = []
    is_rejected = False
    reject_reason = None

    if DEBUG_MODE:
        print(f"  🔍 [structural debug] {token_address[:8]}... inputs:")
        print(f"      holder_data: {holder_data}")
        print(f"      authority_data: {authority_data}")
        print(f"      security_data: {security_data}")
    
    # 1. Check Hard Rejects First
    if authority_data:
        if HARD_REJECTS.get("freeze_authority") and authority_data.get("has_freeze"):
            is_rejected = True
            reject_reason = "🚫 Freeze authority enabled"
        
        if HARD_REJECTS.get("mint_authority") and authority_data.get("has_mint"):
            is_rejected = True
            reject_reason = "🚫 Mint authority enabled"
    
    if security_data:
        if HARD_REJECTS.get("honeypot_detected") and security_data.get("is_honeypot"):
            is_rejected = True
            reject_reason = "🚫 Honeypot detected"
    
    if is_rejected:
        return {
            "score": 0,
            "signals": [reject_reason],
            "is_rejected": True,
            "reject_reason": reject_reason
        }
    
    # 2. Holder Concentration (deduct up to 40 points) — graduated, not a flat cliff.
    # A flat -30/-15 step was collapsing tokens with 21% top-holder and 49%
    # top-holder into the same penalty, which is why structural scores were
    # landing on the same value across very different tokens. This scales
    # the penalty by how far past the danger line the token actually is.
    if holder_data:
        top1 = holder_data.get("top1_percentage", 0)
        top10 = holder_data.get("top10_percentage", 0)
        hard_limit = HARD_REJECTS.get("top_holder_above", 0.5)
        
        # Check against hard reject
        if top1 > hard_limit:
            return {
                "score": 0,
                "signals": [f"🚫 Top holder owns {top1*100:.1f}%"],
                "is_rejected": True,
                "reject_reason": f"Top holder owns {top1*100:.1f}%"
            }
        
        danger = STRUCTURAL_THRESHOLDS["top_holder_danger"]
        warning = STRUCTURAL_THRESHOLDS["top_holder_warning"]
        if top1 > danger:
            severity = min((top1 - danger) / max(hard_limit - danger, 0.01), 1.0)
            penalty = 15 + severity * 25  # scales 15 -> 40 as it approaches the hard limit
            score -= penalty
            signals.append(f"⚠️ Top holder: {top1*100:.1f}%")
        elif top1 > warning:
            severity = (top1 - warning) / max(danger - warning, 0.01)
            penalty = 5 + severity * 10  # scales 5 -> 15
            score -= penalty
            signals.append(f"Top holder: {top1*100:.1f}%")
        
        danger10 = STRUCTURAL_THRESHOLDS["top10_holder_danger"]
        warning10 = STRUCTURAL_THRESHOLDS["top10_holder_warning"]
        if top10 > danger10:
            severity = min((top10 - danger10) / max(1.0 - danger10, 0.01), 1.0)
            penalty = 10 + severity * 20  # scales 10 -> 30
            score -= penalty
            signals.append(f"⚠️ Top 10 own: {top10*100:.1f}%")
        elif top10 > warning10:
            severity = (top10 - warning10) / max(danger10 - warning10, 0.01)
            penalty = 3 + severity * 7  # scales 3 -> 10
            score -= penalty
    
    # 3. Authority Checks (deduct up to 30 points)
    if authority_data:
        if authority_data.get("has_freeze"):
            score -= 20
            signals.append("⚠️ Has freeze authority")
        
        if authority_data.get("has_mint"):
            score -= 15
            signals.append("⚠️ Has mint authority")
        
        if authority_data.get("safe"):
            signals.append("✅ Authorities renounced")
    
    # 4. Security Scan (deduct up to 20 points)
    if security_data:
        if security_data.get("can_freeze"):
            score -= 10
        if security_data.get("is_mintable"):
            score -= 10
        if security_data.get("transfer_pausable"):
            score -= 10
            signals.append("⚠️ Transfers can be paused")

        # LP burn bonus — rewards tokens with locked/burned liquidity,
        # which can't be pulled out by the dev (a common rug vector).
        # lp_burned can be True, False, or None (unknown/unconfirmed).
        lp_burned = security_data.get("lp_burned")
        if lp_burned is True:
            score = min(score + STRUCTURAL_THRESHOLDS["lp_burned_bonus"], 100)
            pct = security_data.get("lp_burned_pct")
            if pct is not None:
                signals.append(f"🔒 LP burned: {pct:.0f}%")
            else:
                signals.append("🔒 LP burned")
        elif lp_burned is False:
            signals.append("⚠️ LP not burned/locked")
        # lp_burned is None -> data unavailable, no score change, no signal
    
    # 5. Liquidity Check
    # This would use current_data if passed, skipping for now
    
    final_score = clamp(score, 0, 100)
    
    if DEBUG_MODE:
        print(f"  🏗️ [structural debug] {token_address[:8]}... final_score={final_score} signals={signals}")
    
    return {
        "score": final_score,
        "signals": signals,
        "is_rejected": False,
        "reject_reason": None
    }


if __name__ == "__main__":
    print("Testing structural.py...")
    
    # Mock safe token
    mock_holders = {"top1_percentage": 0.05, "top10_percentage": 0.25}
    mock_authority = {"has_freeze": False, "has_mint": False, "safe": True}
    mock_security = {"is_honeypot": False, "can_freeze": False}
    
    result = calculate_structural_score("test", mock_holders, mock_authority, mock_security)
    
    print(f"\nStructural Score: {result['score']}/100")
    print(f"Rejected: {result['is_rejected']}")
    print("Signals:")
    for s in result['signals']:
        print(f"  {s}")
    
    # Mock dangerous token
    print("\n--- Testing dangerous token ---")
    mock_holders_bad = {"top1_percentage": 0.55, "top10_percentage": 0.80}
    
    result2 = calculate_structural_score("test", mock_holders_bad, mock_authority, mock_security)
    print(f"Score: {result2['score']}/100")
    print(f"Rejected: {result2['is_rejected']}")
    print(f"Reason: {result2.get('reject_reason')}")
    
    print("\n✅ structural.py working!")