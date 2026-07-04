"""
alert.py - Alert Engine
Combines all engine scores, determines final score and alert tier.

Two independent alert tiers now exist:
1. Fast tier (this file's should_alert/check_fast_alert) — an early,
   unproven ping on a raw buy-volume/buy-count spike, mirroring Ola's
   Aladdin "BIG VOLUME ALERT". Fires within the first few minutes.
2. Formation tier (formation_tracker.py) — a later, higher-confidence
   follow-up once the 10m Early Buy Pressure formation is confirmed
   (volume >= $40k, return >= 2.5x, holders >= 250). Independent of #1;
   doesn't gate it and isn't gated by it.
"""

from config import ENGINE_WEIGHTS, ALERT_THRESHOLDS, FAST_ALERT_SETTINGS, DEBUG_MODE
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


def check_fast_alert(current_data, age_minutes):
    """
    Fast, unproven early ping — mirrors Ola's Aladdin "BIG VOLUME ALERT"
    (observed real hits: 44 SOL/34 buys at 1m, 66 SOL/48 buys at 5m).
    No formation proof required for this one.

    Note: DexScreener's volume_5m is combined buy+sell volume, not a
    pure buy-side figure — this is an approximation of Ola's real
    buy-only SOL volume. Close enough in a token's first few minutes,
    when sell pressure is usually minimal, but worth knowing it's an
    approximation and not an exact match to his numbers.

    Returns (passed: bool, buy_volume_sol: float, buy_count: int).
    """
    if age_minutes is None or age_minutes > FAST_ALERT_SETTINGS["max_age_minutes"]:
        return False, 0, 0

    market_context = db.get_latest_market_context()
    sol_price = market_context.get("sol_price") if market_context else None
    if not sol_price:
        return False, 0, 0

    buy_volume_usd = current_data.get("volume_5m", 0) or 0
    buy_volume_sol = buy_volume_usd / sol_price
    buy_count = current_data.get("buys_5m", 0) or 0

    passed = (
        buy_volume_sol >= FAST_ALERT_SETTINGS["min_buy_volume_sol"]
        and buy_count >= FAST_ALERT_SETTINGS["min_buy_count"]
    )
    return passed, buy_volume_sol, buy_count


def should_alert(token_address, current_data, age_minutes):
    """
    Fast tier gate: fires once, early, on a raw volume/buy-count spike.
    Independent of the composite engine score below — Ola's real alerts
    fire on volume alone, well before there'd be enough data for a
    reliable score. The formation tier (formation_tracker.py) is a
    separate, later, higher-confidence follow-up.
    """
    cooldown = ALERT_THRESHOLDS["alert_cooldown_minutes"]
    if not db.can_alert(token_address, cooldown):
        return False

    if db.get_last_alert(token_address):
        return False  # fast tier only ever fires once per token

    passed, _, _ = check_fast_alert(current_data, age_minutes)
    return passed


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
    
    # Fast tier gate — independent of the score/tier above (see should_alert)
    age_minutes = timing.get("age_minutes", 0)
    should_send = should_alert(token_address, current_data, age_minutes)
    _, buy_volume_sol, buy_count = check_fast_alert(current_data, age_minutes)
    
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
        "buys_5m": current_data.get("buys_5m", 0),
        "sells_5m": current_data.get("sells_5m", 0),
        "holders": current_data.get("holders", 0),
        "buy_volume_sol": round(buy_volume_sol, 1),
        "buy_count": buy_count,
        
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
