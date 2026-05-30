"""
alert.py - Alert Engine
Combines all engine scores, determines final score and alert tier.
"""

from config import ENGINE_WEIGHTS, ALERT_THRESHOLDS, DEBUG_MODE
from helpers import clamp
import database as db


def calculate_final_score(discovery, structural, timing, context, smart_wallet):
    """
    Combines all engine scores using configured weights.
    Returns final score 0-100.
    """
    # Get individual scores
    d_score = discovery.get("score", 50)
    s_score = structural.get("score", 50)
    t_score = timing.get("score", 50)
    c_score = context.get("score", 50)
    w_score = smart_wallet.get("score", 50)
    
    # Apply weights
    weighted = (
        d_score * ENGINE_WEIGHTS["discovery"] +
        s_score * ENGINE_WEIGHTS["structural"] +
        t_score * ENGINE_WEIGHTS["timing"] +
        c_score * ENGINE_WEIGHTS["context"] +
        w_score * ENGINE_WEIGHTS["smart_wallet"]
    )
    
    # Apply timing multiplier
    multiplier = timing.get("multiplier", 1.0)
    final = weighted * multiplier
    
    return clamp(final, 0, 100)


def determine_alert_tier(final_score):
    """
    Determines alert tier based on final score.
    Returns: 1 (high), 2 (medium), 3 (low), or 0 (no alert)
    """
    if final_score >= ALERT_THRESHOLDS["tier1_high"]:
        return 1
    elif final_score >= ALERT_THRESHOLDS["tier2_medium"]:
        return 2
    elif final_score >= ALERT_THRESHOLDS["tier3_low"]:
        return 3
    else:
        return 0


def should_alert(token_address, final_score, tier):
    """
    Checks if we should send an alert (cooldown, score change).
    """
    if tier == 0:
        return False
    
    # Check cooldown
    cooldown = ALERT_THRESHOLDS["alert_cooldown_minutes"]
    if not db.can_alert(token_address, cooldown):
        # Check if score changed significantly
        last_alert = db.get_last_alert(token_address)
        if last_alert:
            score_diff = abs(final_score - last_alert["final_score"])
            if score_diff < ALERT_THRESHOLDS["score_change_for_realert"]:
                return False
    
    return True


def generate_alert_data(token_address, token_data, current_data, 
                        discovery, structural, timing, context, smart_wallet):
    """
    Generates complete alert data package.
    """
    # Check for rejection first
    if structural.get("is_rejected"):
        return {
            "should_alert": False,
            "rejected": True,
            "reject_reason": structural.get("reject_reason"),
            "tier": 0,
            "final_score": 0
        }
    
    # Calculate final score
    final_score = calculate_final_score(
        discovery, structural, timing, context, smart_wallet
    )
    
    # Determine tier
    tier = determine_alert_tier(final_score)
    
    # Check if should alert
    should_send = should_alert(token_address, final_score, tier)
    
    # Compile all signals
    all_signals = []
    all_signals.extend(discovery.get("signals", []))
    all_signals.extend(structural.get("signals", []))
    all_signals.extend(timing.get("signals", []))
    all_signals.extend(smart_wallet.get("signals", []))
    
    alert_data = {
        "should_alert": should_send,
        "rejected": False,
        "tier": tier,
        "final_score": round(final_score, 1),
        "token_address": token_address,
        "symbol": token_data.get("symbol", "???"),
        "name": token_data.get("name", "Unknown"),
        
        # Current metrics
        "price_usd": current_data.get("price_usd", 0),
        "market_cap_usd": current_data.get("market_cap_usd", 0),
        "liquidity_usd": current_data.get("liquidity_usd", 0),
        "volume_5m": current_data.get("volume_5m", 0),
        "holders": current_data.get("holders", 0),
        
        # Engine scores
        "scores": {
            "discovery": discovery.get("score", 0),
            "structural": structural.get("score", 0),
            "timing": timing.get("score", 0),
            "context": context.get("score", 0),
            "smart_wallet": smart_wallet.get("score", 0),
        },
        
        # Timing info
        "timing_grade": timing.get("grade", "?"),
        "age_minutes": timing.get("age_minutes", 0),
        
        # Signals
        "signals": all_signals[:5],  # Top 5 signals
        
        # Smart wallet info
        "smart_wallet_hits": smart_wallet.get("smart_wallet_hits", 0),
        "whale_hits": smart_wallet.get("whale_hits", 0),
    }
    
    if DEBUG_MODE:
        tier_emoji = {1: "🔥", 2: "⚠️", 3: "📊", 0: "⬜"}
        print(f"\n{tier_emoji[tier]} Final Score: {final_score:.1f} (Tier {tier})")
    
    return alert_data


if __name__ == "__main__":
    print("Testing alert.py...")
    
    # Mock engine results
    mock_discovery = {"score": 75, "signals": ["Strong volume"]}
    mock_structural = {"score": 85, "signals": ["Safe token"], "is_rejected": False}
    mock_timing = {"score": 90, "grade": "A", "multiplier": 1.2, "age_minutes": 3, "signals": ["Very early"]}
    mock_context = {"score": 60, "signals": ["Neutral market"]}
    mock_smart = {"score": 70, "signals": ["1 whale buy"], "smart_wallet_hits": 0, "whale_hits": 1}
    
    # Calculate final score
    final = calculate_final_score(
        mock_discovery, mock_structural, mock_timing, mock_context, mock_smart
    )
    
    print(f"\nEngine Scores:")
    print(f"  Discovery:    {mock_discovery['score']}")
    print(f"  Structural:   {mock_structural['score']}")
    print(f"  Timing:       {mock_timing['score']} (Grade {mock_timing['grade']})")
    print(f"  Context:      {mock_context['score']}")
    print(f"  Smart Wallet: {mock_smart['score']}")
    
    print(f"\nFinal Score: {final:.1f}")
    print(f"Tier: {determine_alert_tier(final)}")
    
    # Full alert generation
    print("\n--- Full Alert Test ---")
    mock_token = {"symbol": "TEST", "name": "Test Token"}
    mock_current = {"price_usd": 0.001, "market_cap_usd": 50000, "liquidity_usd": 10000}
    
    alert = generate_alert_data(
        "TestAddress123",
        mock_token,
        mock_current,
        mock_discovery,
        mock_structural,
        mock_timing,
        mock_context,
        mock_smart
    )
    
    print(f"Should Alert: {alert['should_alert']}")
    print(f"Tier: {alert['tier']}")
    print(f"Score: {alert['final_score']}")
    
    print("\n✅ alert.py working!")