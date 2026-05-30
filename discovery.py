"""
discovery.py - Discovery Engine
Detects early momentum: volume acceleration, holder growth, buy pressure.
Weight: 30% of final score
"""

from config import DISCOVERY_THRESHOLDS, DEBUG_MODE
from helpers import safe_divide, calculate_change, clamp
import database as db


def calculate_discovery_score(token_address, current_data, snapshots):
    """
    Calculates discovery score (0-100).
    Measures early acceleration signals.
    """
    score = 0
    signals = []
    
    # Need at least 2 snapshots to measure change
    if len(snapshots) < 2:
        return {"score": 50, "signals": ["Insufficient data"], "raw": {}}
    
    latest = snapshots[-1]
    previous = snapshots[-2]
    oldest = snapshots[0]
    
    # 1. Volume Acceleration (0-30 points)
    vol_current = current_data.get("volume_5m", 0)
    vol_previous = previous.get("volume_5m", 0)
    vol_acceleration = safe_divide(vol_current, vol_previous, 1)
    
    if vol_acceleration >= DISCOVERY_THRESHOLDS["volume_acceleration_strong"]:
        score += 30
        signals.append(f"🔥 Strong volume surge: {vol_acceleration:.1f}x")
    elif vol_acceleration >= DISCOVERY_THRESHOLDS["volume_acceleration_moderate"]:
        score += 20
        signals.append(f"📈 Volume increasing: {vol_acceleration:.1f}x")
    elif vol_acceleration >= 1.0:
        score += 10
        signals.append("Volume stable")
    
    # 2. Buy Pressure (0-25 points)
    buys = current_data.get("buys_5m", 0)
    sells = current_data.get("sells_5m", 0)
    buy_ratio = safe_divide(buys, sells, 1)
    
    if buy_ratio >= DISCOVERY_THRESHOLDS["buy_pressure_strong"]:
        score += 25
        signals.append(f"🟢 Heavy buying: {buy_ratio:.1f}:1 buy/sell")
    elif buy_ratio >= DISCOVERY_THRESHOLDS["buy_pressure_moderate"]:
        score += 15
        signals.append(f"Buyers dominant: {buy_ratio:.1f}:1")
    elif buy_ratio >= 1.0:
        score += 5
    
    # 3. Price Momentum (0-25 points)
    price_change = current_data.get("price_change_5m", 0)
    
    if price_change >= DISCOVERY_THRESHOLDS["price_momentum_strong"]:
        score += 25
        signals.append(f"🚀 Price surging: +{price_change*100:.1f}%")
    elif price_change >= DISCOVERY_THRESHOLDS["price_momentum_moderate"]:
        score += 15
        signals.append(f"Price rising: +{price_change*100:.1f}%")
    elif price_change > 0:
        score += 5
    
    # 4. Transaction Frequency (0-20 points)
    total_txns = buys + sells
    
    if total_txns >= DISCOVERY_THRESHOLDS["tx_frequency_high"]:
        score += 20
        signals.append(f"⚡ High activity: {total_txns} txns/5m")
    elif total_txns >= DISCOVERY_THRESHOLDS["tx_frequency_moderate"]:
        score += 10
        signals.append(f"Active trading: {total_txns} txns/5m")
    
    # Clamp score to 0-100
    final_score = clamp(score, 0, 100)
    
    raw_data = {
        "volume_acceleration": vol_acceleration,
        "buy_ratio": buy_ratio,
        "price_change_5m": price_change,
        "total_txns_5m": total_txns,
    }
    
    if DEBUG_MODE and signals:
        print(f"  📊 Discovery: {final_score} - {', '.join(signals[:2])}")
    
    return {
        "score": final_score,
        "signals": signals,
        "raw": raw_data
    }


if __name__ == "__main__":
    print("Testing discovery.py...")
    
    # Mock data for testing
    mock_current = {
        "volume_5m": 5000,
        "buys_5m": 15,
        "sells_5m": 5,
        "price_change_5m": 0.15,
    }
    
    mock_snapshots = [
        {"volume_5m": 1000},
        {"volume_5m": 2000},
    ]
    
    result = calculate_discovery_score("test", mock_current, mock_snapshots)
    
    print(f"\nDiscovery Score: {result['score']}/100")
    print("Signals:")
    for s in result['signals']:
        print(f"  {s}")
    print("\n✅ discovery.py working!")