"""
config.py - Configuration (values injected via environment variables)
"""

import os

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

TELEGRAM_SETTINGS = {
    "parse_mode": "HTML",
    "disable_preview": True,
    "silent_tier3": True,
}

# ============================================================
# API KEYS
# ============================================================
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")

# ============================================================
# API ENDPOINTS
# ============================================================
HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_API = f"https://api.helius.xyz/v0"
DEXSCREENER_API = "https://api.dexscreener.com/latest"
BIRDEYE_API = "https://public-api.birdeye.so"
GOPLUS_API = "https://api.gopluslabs.io/api/v1"

# ============================================================
# BOT SETTINGS
# ============================================================
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
DATABASE_FILE = os.getenv("DATABASE_FILE", "bot_data.db")
RATE_LIMITS = {
    "dexscreener": 30,
    "helius": 10,
    "birdeye": 5,
    "goplus": 10,
}
# ============================================================
# DISCOVERY SETTINGS
# ============================================================
DISCOVERY_SETTINGS = {
    "min_liquidity_usd": 1000,
    "min_volume_5m_usd": 500,
    "min_holders": 10,
    "min_token_age_minutes": 3,
    "max_token_age_minutes": 10,
    "max_market_cap_usd": 500000,
    "max_liquidity_usd": 100000,
    "track_graduated_only": False,
    "track_bonding_curve": True,
}

# ============================================================
# ALERT THRESHOLDS
# ============================================================
ALERT_THRESHOLDS = {
    "tier1_high": 80,
    "tier2_medium": 65,
    "tier3_low": 35,
    "alert_cooldown_minutes": 30,
    "score_change_for_realert": 10,
}

# ============================================================
# ENGINE WEIGHTS (must sum to 1.0)
# ============================================================
ENGINE_WEIGHTS = {
    "discovery": 0.30,
    "structural": 0.25,
    "timing": 0.20,
    "context": 0.10,
    "smart_wallet": 0.15,
}

# ============================================================
# SCAN INTERVALS (seconds)
# ============================================================
SCAN_INTERVALS = {
    "new_token_scan": 10,
    "snapshot_update": 30,
    "market_context_update": 300,
    "cleanup_old_data": 3600,
}

# ============================================================
# TIMING GRADES
# ============================================================
TIMING_GRADES = {
    "A": {"max_age": 5,      "label": "Very Early", "multiplier": 1.2},
    "B": {"max_age": 15,     "label": "Early",      "multiplier": 1.1},
    "C": {"max_age": 30,     "label": "Mid",        "multiplier": 1.0},
    "D": {"max_age": 60,     "label": "Late",       "multiplier": 0.8},
    "F": {"max_age": 999999, "label": "Very Late",  "multiplier": 0.5},
    "holders_early": 50,
    "holders_mid": 200,
    "holders_late": 500,
}

# ============================================================
# DISCOVERY THRESHOLDS
# ============================================================
DISCOVERY_THRESHOLDS = {
    "volume_acceleration_strong": 3.0,
    "volume_acceleration_moderate": 1.5,
    "holder_growth_fast": 5,
    "holder_growth_moderate": 2,
    "buy_pressure_strong": 2.0,
    "buy_pressure_moderate": 1.3,
    "price_momentum_strong": 0.20,
    "price_momentum_moderate": 0.10,
    "tx_frequency_high": 10,
    "tx_frequency_moderate": 5,
}

# ============================================================
# HARD REJECTS
# ============================================================
HARD_REJECTS = {
    "mint_authority": False,
    "freeze_authority": False,
    "honeypot": True,
    "top_holder_above": 0.5,
}
# ============================================================
# STRUCTURAL THRESHOLDS
# ============================================================
STRUCTURAL_THRESHOLDS = {
    "min_liquidity_usd": 1000,
    "max_top10_holder_pct": 80,
    "min_holder_count": 10,
    "max_dev_hold_pct": 20,
    "lp_burned_bonus": 15,
    "verified_bonus": 10,
    "top_holder_danger": 0.20,
    "top_holder_warning": 0.10,
    "top10_holder_danger": 0.60,
    "top10_holder_warning": 0.40,
}
# ============================================================
# LINK TEMPLATES
# ============================================================
LINK_TEMPLATES = {
    "dexscreener": "https://dexscreener.com/solana/{address}",
    "birdeye": "https://birdeye.so/token/{address}?chain=solana",
    "solscan": "https://solscan.io/token/{address}",
}

# ============================================================
# SMART WALLET SETTINGS
# ============================================================
SMART_WALLET_SETTINGS = {
    "min_appearances": 2,
    "score_boost_per_appearance": 10,
    "max_boost": 30,
}
# ============================================================
# CONTEXT SETTINGS
# ============================================================
CONTEXT_SETTINGS = {
    "market_trend_window": 300,
    "volume_baseline_window": 3600,
    "sentiment_weight": 0.3,
    "trend_weight": 0.7,
    "sol_bullish_threshold": 3.0,
    "sol_bearish_threshold": -3.0,
}

# ============================================================
# VALIDATION
# ============================================================
def validate_config():
    errors = []
    warnings = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append("❌ TELEGRAM_BOT_TOKEN not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("❌ TELEGRAM_CHAT_ID not set")
    if not HELIUS_API_KEY:
        warnings.append("⚠️ HELIUS_API_KEY not set - some features disabled")
    if not BIRDEYE_API_KEY:
        warnings.append("⚠️ BIRDEYE_API_KEY not set - holder data unavailable")

    for w in warnings:
        print(w)

    return errors


def print_config_summary():
    tier1 = ALERT_THRESHOLDS['tier1_high']
    tier2 = ALERT_THRESHOLDS['tier2_medium']
    tier3 = ALERT_THRESHOLDS['tier3_low']

    print("=" * 60)
    print("📋 BOT CONFIGURATION SUMMARY")
    print("=" * 60)
    print(f"Telegram Enabled: {TELEGRAM_ENABLED}")
    print(f"Debug Mode: {DEBUG_MODE}")
    print(f"\nDiscovery Settings:")
    print(f"  Min Liquidity: ${DISCOVERY_SETTINGS['min_liquidity_usd']:,}")
    print(f"  Max Token Age: {DISCOVERY_SETTINGS['max_token_age_minutes']} minutes")
    print(f"\nAlert Thresholds:")
    print(f"  🔥 Tier 1 (High): {tier1}+")
    print(f"  ⚠️ Tier 2 (Medium): {tier2}+")
    print(f"  📊 Tier 3 (Low): {tier3}+")
    print(f"\nEngine Weights:")
    for engine, weight in ENGINE_WEIGHTS.items():
        print(f"  {engine}: {weight*100:.0f}%")
    print("=" * 60)
