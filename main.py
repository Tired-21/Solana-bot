"""
main.py - Main Entry Point
Runs the signal bot: discovers tokens, scores them, sends alerts.
"""

import time
import traceback
from datetime import datetime
# Config and database
from config import (
    SCAN_INTERVALS, DISCOVERY_SETTINGS, DEBUG_MODE,
    TELEGRAM_ENABLED, validate_config, print_config_summary
)
import database as db

# Data sources
from dexscreener import get_token_data, search_tokens
from pumpfun import get_new_tokens, get_graduating_tokens
from jupiter import get_sol_price
from helius import check_authorities
from birdeye import get_holder_distribution, get_token_overview
from goplus import get_token_security

# Engines
from discovery import calculate_discovery_score
from structural import calculate_structural_score
from timing import calculate_timing_score
from context import update_market_context, calculate_context_score
from smart_wallet import calculate_smart_wallet_score
from alert import generate_alert_data

# Telegram
from telegram_bot import send_alert, send_startup_message, send_message, send_x_alert, send_daily_digest, start_command_listener, bot_state

# Helpers
from helpers import format_number, truncate_address

# Track which X milestones have been sent per token
# Format: {token_address: set of multipliers already alerted}
x_alerts_sent = {}  # token_address -> last alerted multiplier (e.g. 2, 4, 8, 16...)


def log(message):
    """Prints timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def passes_discovery_filter(token, source="unknown"):
    """Checks if token passes minimum requirements."""
    if not token or not token.get("address"):
        return False

    liq = float(token.get("liquidity_usd") or token.get("liquidity") or 0)
    mc = float(token.get("market_cap_usd") or token.get("market_cap") or 0)

    # Minimum token age
    age = token.get("created_timestamp")
    if age:
        age_minutes = (time.time() - age / 1000) / 60
        if age_minutes < DISCOVERY_SETTINGS.get("min_token_age_minutes", 3):
            return False

    # Minimum liquidity
    if liq < DISCOVERY_SETTINGS["min_liquidity_usd"]:
        return False

    # Maximum market cap
    if mc > DISCOVERY_SETTINGS["max_market_cap_usd"]:
        return False

    # Maximum liquidity
    if liq > DISCOVERY_SETTINGS["max_liquidity_usd"]:
        return False

    return True


def check_x_alert(token_address, symbol, name, mc_now):
    """Checks if MC has doubled again since the last X-alert (continuous: 2x, 4x, 8x, 16x...)."""
    last_alert = db.get_last_alert(token_address)
    if not last_alert:
        return

    mc_at_alert = last_alert.get("market_cap_at_alert", 0)
    if not mc_at_alert or mc_at_alert == 0:
        return

    multiplier = mc_now / mc_at_alert

    # Initialize tracking for this token — next target starts at 2x
    if token_address not in x_alerts_sent:
        x_alerts_sent[token_address] = 1  # last confirmed multiplier (1x = baseline)

    last_milestone = x_alerts_sent[token_address]
    next_target = last_milestone * 2

    # Keep firing while the current multiplier has cleared the next doubling
    while multiplier >= next_target:
        x_alerts_sent[token_address] = next_target
        log(f"🚀 {symbol} hit {next_target}x! MC: ${mc_now:,.0f}")
        alert_time = last_alert.get("timestamp", 0)
        minutes_elapsed = (time.time() - alert_time) / 60 if alert_time else 0

        send_x_alert(
            symbol=symbol,
            name=name,
            addr=token_address,
            multiplier=next_target,
            mc_now=mc_now,
            mc_at_alert=mc_at_alert,
            minutes_elapsed=minutes_elapsed
        )

        last_milestone = next_target
        next_target = last_milestone * 2


def discover_new_tokens():
    """Finds new tokens to track."""
    new_tokens = []

    # Try Pump.fun first
    pumpfun_tokens = get_new_tokens(limit=20)

    for token in pumpfun_tokens:
        if passes_discovery_filter(token, source="pumpfun"):
            new_tokens.append(token)

    # Also check DexScreener
    dex_results = search_tokens("pump.fun")
    for token in dex_results[:10]:
        if token and passes_discovery_filter(token, source="dexscreener"):
            existing = db.get_token(token["address"])
            if not existing:
                new_tokens.append(token)

    return new_tokens


def process_token(token_address):
    """
    Processes a single token through all engines.
    Returns alert data or None.
    """
    if DEBUG_MODE:
        log(f"Processing: {truncate_address(token_address)}")

    # 1. Get current data from DexScreener
    current_data = get_token_data(token_address)
    if not current_data:
        if DEBUG_MODE:
            log(f"  ❌ No DexScreener data")
        return None

    # 2. Get token from database
    token_data = db.get_token(token_address)
    if not token_data:
        db.add_token(
            address=token_address,
            symbol=current_data.get("symbol"),
            name=current_data.get("name"),
            liquidity_usd=current_data.get("liquidity_usd"),
            market_cap_usd=current_data.get("market_cap_usd"),
            created_at=current_data.get("pair_created_at")
        )
        token_data = db.get_token(token_address)

    # 3. Save snapshot
    db.add_snapshot(
        token_address=token_address,
        price_usd=current_data.get("price_usd", 0),
        volume_5m=current_data.get("volume_5m", 0),
        volume_1h=current_data.get("volume_1h", 0),
        liquidity_usd=current_data.get("liquidity_usd", 0),
        market_cap_usd=current_data.get("market_cap_usd", 0),
        holders=current_data.get("holders", 0),
        buys_5m=current_data.get("buys_5m", 0),
        sells_5m=current_data.get("sells_5m", 0)
    )

    # 4. Get historical snapshots
    snapshots = db.get_recent_snapshots(token_address, minutes=30)

    # 5. Get additional data
    # Check security cache first to save Helius API credits
    cached = db.get_security_cache(token_address, max_age_minutes=120)
    if cached:
        authority_data = {
            "has_freeze": bool(cached.get("has_freeze")),
            "has_mint": bool(cached.get("has_mint")),
            "safe": not cached.get("has_freeze") and not cached.get("has_mint")
        }
        security_data = {
            "is_honeypot": bool(cached.get("is_honeypot")),
            "can_freeze": bool(cached.get("has_freeze")),
            "is_mintable": bool(cached.get("has_mint")),
            "transfer_pausable": False
        }
    else:
        authority_data = check_authorities(token_address)
        security_data = get_token_security(token_address)
        db.cache_security_scan(
            token_address=token_address,
            is_honeypot=security_data.get("is_honeypot", False) if security_data else False,
            has_freeze=authority_data.get("has_freeze", False) if authority_data else False,
            has_mint=authority_data.get("has_mint", False) if authority_data else False,
            top_holder_pct=0
        )
    holder_data = get_holder_distribution(token_address)

    # 6. Run all engines
    discovery_result = calculate_discovery_score(token_address, current_data, snapshots)

    structural_result = calculate_structural_score(
        token_address, holder_data, authority_data, security_data
    )

    # Check for hard reject
    if structural_result.get("is_rejected"):
        if DEBUG_MODE:
            log(f"  🚫 Rejected: {structural_result.get('reject_reason')}")
        db.update_token_status(token_address, "rejected")
        return None

    timing_result = calculate_timing_score(token_address, token_data, current_data)
    context_result = calculate_context_score()
    smart_wallet_result = calculate_smart_wallet_score(token_address, recent_buyers=None)

    # 7. Check X alerts for tracked tokens
    mc_now = current_data.get("market_cap_usd", 0)
    if mc_now > 0:
        check_x_alert(
            token_address=token_address,
            symbol=token_data.get("symbol", "???"),
            name=token_data.get("name", ""),
            mc_now=mc_now
        )

    # 8. Generate alert data
    alert_data = generate_alert_data(
        token_address=token_address,
        token_data=token_data,
        current_data=current_data,
        discovery=discovery_result,
        structural=structural_result,
        timing=timing_result,
        context=context_result,
        smart_wallet=smart_wallet_result
    )

    # 9. Save score to database
    db.add_score(
        token_address=token_address,
        discovery=discovery_result["score"],
        structural=structural_result["score"],
        timing=timing_result["score"],
        context=context_result["score"],
        smart_wallet=smart_wallet_result["score"],
        final=alert_data["final_score"],
        timing_grade=timing_result["grade"]
    )

    return alert_data


def process_alert(alert_data):
    """Sends alert and records it."""
    if not alert_data.get("should_alert"):
        return

    tier = alert_data["tier"]
    token_address = alert_data["token_address"]

    tier_names = {1: "🔥 HIGH", 2: "⚠️ WATCH", 3: "📊 MONITOR"}
    log(f"{tier_names.get(tier, '?')} ALERT: ${alert_data['symbol']} (Score: {alert_data['final_score']})")

    message_id = send_alert(alert_data)

    alert_id = db.add_alert(
        token_address=token_address,
        tier=tier,
        final_score=alert_data["final_score"],
        price_at_alert=alert_data["price_usd"],
        market_cap_at_alert=alert_data["market_cap_usd"],
        message_id=str(message_id) if message_id else None
    )

    db.add_outcome(alert_id, token_address, alert_data["price_usd"])


def run_scan_cycle():
    """Runs one complete scan cycle."""

    log("🔍 Scanning for new tokens...")
    new_tokens = discover_new_tokens()

    if new_tokens:
        log(f"  Found {len(new_tokens)} new tokens")
        for token in new_tokens[:5]:
            try:
                alert_data = process_token(token["address"])
                if alert_data:
                    process_alert(alert_data)
            except Exception as e:
                if DEBUG_MODE:
                    log(f"  ❌ Error processing {token.get('symbol', '?')}: {e}")

    active_tokens = db.get_active_tokens()
    bot_state["tokens_tracked"] = len(active_tokens)
    # Skip tokens just processed as new to avoid double alerts
    new_addresses = {t["address"] for t in new_tokens} if new_tokens else set()
    if active_tokens:
        log(f"📡 Updating {len(active_tokens)} tracked tokens...")
        for token in active_tokens:
            if token["address"] in new_addresses:
                continue
            try:
                alert_data = process_token(token["address"])
                if alert_data:
                    process_alert(alert_data)
            except Exception as e:
                if DEBUG_MODE:
                    log(f"  ❌ Error updating {token.get('symbol', '?')}: {e}")


def run_daily_digest():
    """Builds and sends the 24h leaderboard digest."""
    log("📊 Building daily digest...")
    alerts = db.get_alerts_in_window(hours=24)

    entries = []
    for a in alerts:
        peak_mc = db.get_peak_market_cap(a["token_address"], since_timestamp=a["timestamp"])
        # Peak should never be lower than the alert-time MC itself
        peak_mc = max(peak_mc, a.get("market_cap_at_alert", 0) or 0)
        entries.append({
            "symbol": a.get("symbol"),
            "name": a.get("name"),
            "market_cap_at_alert": a.get("market_cap_at_alert", 0),
            "peak_market_cap": peak_mc,
        })

    send_daily_digest(entries)
    log(f"📊 Daily digest sent ({len(entries)} tokens)")


def main():
    """Main entry point."""
    print("\n" + "="*50)
    print("🚀 SOLANA MEMECOIN SIGNAL BOT")
    print("="*50)

    errors = validate_config()
    if errors:
        print("\n⚠️ Configuration Issues:")
        for e in errors:
            print(f"  {e}")
        critical = [e for e in errors if e.startswith("❌")]
        if critical:
            print("\n❌ Fix critical errors before running!")
            return

    print_config_summary()

    log("Initializing database...")
    db.init_database()

    log("Fetching market context...")
    update_market_context()

    if TELEGRAM_ENABLED:
        log("Sending startup message to Telegram...")
        send_startup_message()
        start_command_listener()
        log("🎧 Command listener active (/stop /start /status)")

    last_scan = 0
    last_context_update = 0
    last_cleanup = 0
    last_digest = time.time()
    cycle_count = 0

    log("✅ Bot started! Monitoring for opportunities...\n")

    try:
        while True:
            # Command-based pause check
            if not bot_state["scanning"]:
                time.sleep(1)
                continue
            now = time.time()

            if now - last_scan >= SCAN_INTERVALS["new_token_scan"]:
                cycle_count += 1
                if DEBUG_MODE:
                    log(f"--- Cycle {cycle_count} ---")
                try:
                    run_scan_cycle()
                    bot_state["last_scan"] = now
                except Exception as e:
                    log(f"❌ Scan cycle error: {e}")
                    if DEBUG_MODE:
                        traceback.print_exc()
                last_scan = now

            if now - last_context_update >= SCAN_INTERVALS["market_context_update"]:
                try:
                    update_market_context()
                except Exception as e:
                    if DEBUG_MODE:
                        log(f"❌ Context update error: {e}")
                last_context_update = now

            if now - last_cleanup >= SCAN_INTERVALS["cleanup_old_data"]:
                try:
                    db.cleanup_old_data(days=7)
                except Exception as e:
                    if DEBUG_MODE:
                        log(f"❌ Cleanup error: {e}")
                last_cleanup = now

            if now - last_digest >= SCAN_INTERVALS["daily_digest"]:
                try:
                    run_daily_digest()
                except Exception as e:
                    log(f"❌ Daily digest error: {e}")
                    if DEBUG_MODE:
                        traceback.print_exc()
                last_digest = now

            if bot_state.get("digest_requested"):
                bot_state["digest_requested"] = False
                try:
                    run_daily_digest()
                except Exception as e:
                    log(f"❌ Manual digest error: {e}")
                    if DEBUG_MODE:
                        traceback.print_exc()

            time.sleep(1)

    except KeyboardInterrupt:
        log("\n🛑 Bot stopped by user")
        if TELEGRAM_ENABLED:
            send_message("🛑 <b>Bot stopped</b>")
    except Exception as e:
        log(f"\n❌ Fatal error: {e}")
        traceback.print_exc()
        if TELEGRAM_ENABLED:
            send_message(f"❌ <b>Bot crashed:</b> {str(e)[:100]}")


if __name__ == "__main__":
    main()
