"""
context.py - Buy Pressure Engine
Scores token-specific buying behavior using data already available
from DexScreener every cycle. No new API calls.

Replaces the old SOL market regime score which was identical for every
token scanned in the same session (permanently 50 in neutral markets).

Weight: 20% of final score

Three signals, each scored independently then combined:

1. Volume per buy (avg buy size) — conviction proxy
   Ola's alerts show SOL-per-buy as the primary signal.
   High avg buy size = real money, not bot noise.

2. Buy/sell ratio — momentum direction
   Raw ratio from DexScreener buys_5m / sells_5m.

3. Volume acceleration — is momentum growing?
   Compares current 5m volume to previous snapshot.
   Rising = accelerating, flat/falling = fading.
"""

import time
from config import DEBUG_MODE
from helpers import clamp


def calculate_context_score(current_data=None, snapshots=None):
    """
    Calculates buy pressure score (0-100) from token-specific data.
    Higher = stronger buying conviction and momentum.

    Args:
        current_data: latest DexScreener snapshot dict for this token
        snapshots: list of recent DB snapshots (from get_recent_snapshots)
    """
    if not current_data:
        return {"score": 50, "signals": ["No token data"], "regime": "unknown"}

    signals = []
    score = 50  # neutral baseline

    buys = current_data.get("buys_5m") or 0
    sells = current_data.get("sells_5m") or 0
    volume = current_data.get("volume_5m") or 0

    # =========================================================
    # 1. AVERAGE BUY SIZE — conviction proxy (up to +25 / -15)
    # =========================================================
    # DAD: $35K / 34 buys = ~$1K avg. Glippy: $27K / 48 buys = ~$562 avg.
    # These are real entries. $50 avg buys = bots/noise.
    avg_buy_size = (volume / buys) if buys > 0 else 0

    if avg_buy_size >= 800:
        score += 25
        signals.append(f"💰 Avg buy ${avg_buy_size:,.0f} — high conviction")
    elif avg_buy_size >= 400:
        score += 18
        signals.append(f"💰 Avg buy ${avg_buy_size:,.0f}")
    elif avg_buy_size >= 200:
        score += 10
        signals.append(f"Avg buy ${avg_buy_size:,.0f}")
    elif avg_buy_size >= 80:
        score += 3
    elif avg_buy_size > 0:
        score -= 8
        signals.append(f"⚠️ Avg buy ${avg_buy_size:,.0f} — low conviction")
    # avg_buy_size == 0 means no buys, no change

    # =========================================================
    # 2. BUY/SELL RATIO — momentum direction (up to +20 / -15)
    # =========================================================
    if sells == 0 and buys > 0:
        ratio = buys  # treat pure buys as very high ratio
    elif sells > 0:
        ratio = buys / sells
    else:
        ratio = 1.0

    if ratio >= 3.0:
        score += 20
        signals.append(f"📈 Buy/sell {ratio:.1f}x — strong buy pressure")
    elif ratio >= 2.0:
        score += 13
        signals.append(f"📈 Buy/sell {ratio:.1f}x")
    elif ratio >= 1.3:
        score += 6
    elif ratio >= 0.8:
        pass  # roughly balanced, no change
    elif ratio >= 0.5:
        score -= 8
        signals.append(f"⚠️ Buy/sell {ratio:.1f}x — sell pressure")
    else:
        score -= 15
        signals.append(f"🔴 Buy/sell {ratio:.1f}x — heavy selling")

    # =========================================================
    # 3. VOLUME ACCELERATION — is momentum growing? (up to +15 / -10)
    # =========================================================
    if snapshots and len(snapshots) >= 2:
        # Compare most recent snapshot volume to the one before it
        prev_volume = snapshots[-2].get("volume_5m") or 0
        curr_volume = snapshots[-1].get("volume_5m") or 0

        if prev_volume > 0:
            accel = (curr_volume - prev_volume) / prev_volume
            if accel >= 0.5:
                score += 15
                signals.append(f"🚀 Volume up {accel*100:.0f}% vs last scan")
            elif accel >= 0.2:
                score += 8
                signals.append(f"↑ Volume up {accel*100:.0f}%")
            elif accel >= -0.1:
                pass  # stable, no change
            elif accel >= -0.4:
                score -= 5
            else:
                score -= 10
                signals.append(f"↓ Volume fading {accel*100:.0f}%")
        # prev_volume == 0: first real snapshot, no acceleration data yet

    final_score = clamp(score, 0, 100)

    if DEBUG_MODE:
        print(
            f"  💹 [context] avg_buy=${avg_buy_size:,.0f} | "
            f"b/s={ratio:.1f} | vol={volume:,.0f} | score={final_score}"
        )

    return {
        "score": final_score,
        "signals": signals,
        "regime": "token",  # kept for API compatibility with main.py
        "multiplier": 1.0,  # kept for API compatibility
    }


# update_market_context kept as no-op so main.py import doesn't break
def update_market_context():
    return None


def get_context_multiplier():
    return 1.0


if __name__ == "__main__":
    print("Testing context.py (buy pressure engine)...")

    # Simulate a hot token — large buys, strong ratio, accelerating
    hot = {
        "buys_5m": 48, "sells_5m": 12, "volume_5m": 27000
    }
    hot_snaps = [
        {"volume_5m": 8000},
        {"volume_5m": 27000},
    ]
    r1 = calculate_context_score(hot, hot_snaps)
    print(f"\nHot token (Glippy-like): {r1['score']}/100")
    for s in r1["signals"]:
        print(f"  {s}")

    # Simulate noise — tiny buys, balanced ratio, flat volume
    noise = {
        "buys_5m": 42, "sells_5m": 30, "volume_5m": 1800
    }
    noise_snaps = [
        {"volume_5m": 1900},
        {"volume_5m": 1800},
    ]
    r2 = calculate_context_score(noise, noise_snaps)
    print(f"\nNoise token: {r2['score']}/100")
    for s in r2["signals"]:
        print(f"  {s}")

    # Simulate sell pressure
    dump = {
        "buys_5m": 20, "sells_5m": 80, "volume_5m": 5000
    }
    r3 = calculate_context_score(dump, None)
    print(f"\nDump token: {r3['score']}/100")
    for s in r3["signals"]:
        print(f"  {s}")

    print("\n✅ context.py working!")
