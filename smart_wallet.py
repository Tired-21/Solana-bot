"""
smart_wallet.py - Smart Wallet Engine
Tracks profitable wallets, detects smart money entries.
Weight: 15% of final score
"""

from config import SMART_WALLET_SETTINGS, DEBUG_MODE
from helpers import clamp
import database as db


def calculate_smart_wallet_score(token_address, recent_buyers=None):
    """
    Calculates smart wallet score (0-100).
    Boosts score when known profitable wallets buy.
    """
    signals = []
    boost = 0
    smart_hits = 0
    whale_hits = 0
    
    if not recent_buyers:
        return {
            "score": 50,
            "signals": ["No buyer data"],
            "smart_wallet_hits": 0,
            "whale_hits": 0
        }
    
    # Check each buyer against smart wallet database
    for buyer in recent_buyers:
        wallet = buyer.get("address")
        amount_usd = buyer.get("amount_usd", 0)
        
        if not wallet:
            continue
        
        # Check if smart wallet
        if db.is_smart_wallet(wallet):
            smart_hits += 1
            boost += SMART_WALLET_SETTINGS["smart_wallet_hit_boost"]
            signals.append(f"🧠 Smart wallet entry: {wallet[:8]}...")
        
        # Check if whale buy
        if amount_usd >= SMART_WALLET_SETTINGS["whale_buy_usd"]:
            whale_hits += 1
            boost += SMART_WALLET_SETTINGS["whale_buy_boost"]
            signals.append(f"🐋 Whale buy: ${amount_usd:,.0f}")
    
    # Cap the boost
    boost = min(boost, SMART_WALLET_SETTINGS["max_smart_wallet_boost"])
    
    # Base score + boost
    score = clamp(50 + boost, 0, 100)
    
    if smart_hits > 0:
        signals.insert(0, f"🎯 {smart_hits} smart wallet(s) detected")
    
    if DEBUG_MODE and (smart_hits > 0 or whale_hits > 0):
        print(f"  🧠 Smart Wallet: {score} ({smart_hits} smart, {whale_hits} whales)")
    
    return {
        "score": score,
        "signals": signals,
        "smart_wallet_hits": smart_hits,
        "whale_hits": whale_hits,
        "boost": boost
    }


def add_smart_wallet(address, total_trades, winning_trades, avg_profit):
    """Adds or updates a smart wallet."""
    if total_trades < SMART_WALLET_SETTINGS["min_trades_to_qualify"]:
        return False
    
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    if win_rate < SMART_WALLET_SETTINGS["min_win_rate"]:
        return False
    
    if avg_profit < SMART_WALLET_SETTINGS["min_avg_profit"]:
        return False
    
    db.upsert_smart_wallet(address, total_trades, winning_trades, win_rate, avg_profit)
    
    if DEBUG_MODE:
        print(f"  ✅ Added smart wallet: {address[:8]}... (WR: {win_rate*100:.0f}%)")
    
    return True


def get_smart_wallet_stats():
    """Returns stats about tracked smart wallets."""
    wallets = db.get_smart_wallets()
    
    if not wallets:
        return {"count": 0, "avg_win_rate": 0, "avg_profit": 0}
    
    avg_wr = sum(w["win_rate"] for w in wallets) / len(wallets)
    avg_profit = sum(w["avg_profit"] for w in wallets) / len(wallets)
    
    return {
        "count": len(wallets),
        "avg_win_rate": avg_wr,
        "avg_profit": avg_profit
    }


if __name__ == "__main__":
    print("Testing smart_wallet.py...")
    
    db.init_database()
    
    # Add a test smart wallet
    print("\nAdding test smart wallet...")
    added = add_smart_wallet(
        address="TestWallet123456789abcdef",
        total_trades=20,
        winning_trades=14,
        avg_profit=0.35
    )
    print(f"  Added: {added}")
    
    # Test scoring with mock buyers
    print("\nTesting score calculation...")
    mock_buyers = [
        {"address": "RandomWallet1", "amount_usd": 500},
        {"address": "RandomWallet2", "amount_usd": 2000},  # Whale
    ]
    
    result = calculate_smart_wallet_score("test_token", mock_buyers)
    
    print(f"  Score: {result['score']}/100")
    print(f"  Smart hits: {result['smart_wallet_hits']}")
    print(f"  Whale hits: {result['whale_hits']}")
    
    # Get stats
    stats = get_smart_wallet_stats()
    print(f"\nSmart Wallet Stats:")
    print(f"  Total tracked: {stats['count']}")
    
    print("\n✅ smart_wallet.py working!")