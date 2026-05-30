"""
context.py - Context Engine
Market conditions: SOL price, regime detection, threshold adjustments.
Weight: 10% of final score
"""

import time
from config import CONTEXT_SETTINGS, DEBUG_MODE
from helpers import clamp
import database as db
from jupiter import get_sol_price


def update_market_context():
    """Fetches and stores current market context."""
    sol_price = get_sol_price()
    
    if not sol_price:
        return None
    
    # Get previous context to calculate change
    prev = db.get_latest_market_context()
    
    if prev and prev.get("sol_price"):
        sol_change_24h = (sol_price - prev["sol_price"]) / prev["sol_price"]
    else:
        sol_change_24h = 0
    
    # Determine market regime
    if sol_change_24h >= CONTEXT_SETTINGS["sol_bullish_threshold"]:
        regime = "bullish"
    elif sol_change_24h <= CONTEXT_SETTINGS["sol_bearish_threshold"]:
        regime = "bearish"
    else:
        regime = "neutral"
    
    # Store in database
    db.add_market_context(sol_price, sol_change_24h, regime)
    
    if DEBUG_MODE:
        print(f"  🌍 Market: SOL ${sol_price:.2f} | {regime}")
    
    return {
        "sol_price": sol_price,
        "sol_change_24h": sol_change_24h,
        "regime": regime
    }


def get_context_multiplier():
    """Returns threshold multiplier based on market conditions."""
    context = db.get_latest_market_context()
    
    if not context:
        return CONTEXT_SETTINGS["neutral_multiplier"]
    
    regime = context.get("market_regime", "neutral")
    
    if regime == "bullish":
        return CONTEXT_SETTINGS["bullish_multiplier"]
    elif regime == "bearish":
        return CONTEXT_SETTINGS["bearish_multiplier"]
    else:
        return CONTEXT_SETTINGS["neutral_multiplier"]


def calculate_context_score():
    """
    Calculates context score (0-100).
    Bullish = higher score, Bearish = lower score.
    """
    context = db.get_latest_market_context()
    
    if not context:
        return {"score": 50, "regime": "unknown", "signals": ["No market data"]}
    
    regime = context.get("market_regime", "neutral")
    sol_change = context.get("sol_change_24h", 0)
    
    signals = []
    
    if regime == "bullish":
        score = 80
        signals.append(f"🟢 Bullish market (SOL +{sol_change*100:.1f}%)")
    elif regime == "bearish":
        score = 30
        signals.append(f"🔴 Bearish market (SOL {sol_change*100:.1f}%)")
    else:
        score = 50
        signals.append(f"⚪ Neutral market (SOL {sol_change*100:+.1f}%)")
    
    if DEBUG_MODE:
        print(f"  🌍 Context: {score} - {regime}")
    
    return {
        "score": score,
        "regime": regime,
        "multiplier": get_context_multiplier(),
        "signals": signals
    }


if __name__ == "__main__":
    print("Testing context.py...")
    
    # Initialize database
    db.init_database()
    
    print("\nUpdating market context...")
    context = update_market_context()
    
    if context:
        print(f"  SOL Price: ${context['sol_price']:.2f}")
        print(f"  24h Change: {context['sol_change_24h']*100:+.1f}%")
        print(f"  Regime: {context['regime']}")
        
        print("\nCalculating context score...")
        result = calculate_context_score()
        print(f"  Score: {result['score']}/100")
        print(f"  Multiplier: {result['multiplier']}x")
        
        print("\n✅ context.py working!")
    else:
        print("❌ Failed to get market context")