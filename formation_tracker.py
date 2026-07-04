"""
formation_tracker.py - Formation Window Tracker
================================================
Tracks every non-rejected token at fixed checkpoints (1m, 5m, 10m, 15m,
30m, 60m) after discovery, recording FDV, volume, holder count, buy/sell
counts, and migration status at each checkpoint.

Formation-gated mode: no alert fires on discovery anymore (see
alert.py's should_alert). Tokens are tracked silently from first_seen.
At the 10m checkpoint, if Ola's validated "Early Buy Pressure" formation
is confirmed (10m volume >= $40k, 10m return >= 2.5x, 10m holders >= 250
— 6.13x lift over baseline, validated on 222 historical matches), this
module fires the real Telegram alert and records it in the alerts
table. This is now the only alert path in the bot.

Called from main.py's scan loop for every tracked (non-rejected) token.
"""

import time
from config import DEBUG_MODE
import database as db
from telegram_bot import send_alert

FORMATION_WINDOWS = [1, 5, 10, 15, 30, 60]  # minutes post-discovery


def update_formation_windows(token_address, start_timestamp, current_data):
    """
    For a given tracked token, checks which formation windows have elapsed
    since discovery (start_timestamp), and records any that haven't been
    captured yet.

    Called every scan cycle for all tracked (non-rejected) tokens.
    current_data: the token's latest DexScreener snapshot.
    """
    if not start_timestamp or not current_data:
        return

    now = time.time()
    elapsed_minutes = (now - start_timestamp) / 60

    # Baseline FDV = the token's market cap at discovery (stored once on
    # the tokens row when it was first added). Nothing alerts on
    # discovery anymore, so there's no "alert_fdv_usd" to lean on —
    # this is the correct replacement baseline for the return calc.
    token_row = db.get_token(token_address)
    baseline_fdv = (token_row.get("market_cap_usd") if token_row else None) \
        or current_data.get("market_cap_usd", 0) or 0
    if not baseline_fdv:
        return

    # Determine migration status from dex_id
    dex_id = current_data.get("dex_id", "") or ""
    is_migrated = "raydium" in dex_id.lower()
    minutes_to_migration = None

    existing_windows = db.get_formation_windows(token_address)

    if is_migrated:
        for w in existing_windows:
            if w.get("is_migrated") and w.get("minutes_to_migration") is not None:
                minutes_to_migration = w["minutes_to_migration"]
                break
        if minutes_to_migration is None:
            minutes_to_migration = round(elapsed_minutes, 2)

    already_recorded = {w["window_minutes"] for w in existing_windows}

    for window in FORMATION_WINDOWS:
        if window > elapsed_minutes:
            continue
        if window in already_recorded:
            continue

        current_fdv = current_data.get("market_cap_usd", 0) or 0
        fdv_return = (current_fdv / baseline_fdv) if baseline_fdv > 0 else 0

        db.add_formation_window(
            token_address=token_address,
            alert_timestamp=int(start_timestamp),
            window_minutes=window,
            fdv_usd=current_fdv,
            fdv_return=round(fdv_return, 4),
            volume_usd=current_data.get("volume_5m", 0) or 0,
            holder_count=current_data.get("holders", 0) or 0,
            buy_count=current_data.get("buys_5m", 0) or 0,
            sell_count=current_data.get("sells_5m", 0) or 0,
            is_migrated=is_migrated,
            minutes_to_migration=minutes_to_migration,
        )

        if DEBUG_MODE:
            print(
                f"  📊 Formation {window}m: {token_address[:8]}... "
                f"FDV ${current_fdv:,.0f} | "
                f"Return {fdv_return:.2f}x | "
                f"Migrated: {is_migrated}"
            )

        # 10m is the alert gate — nothing has fired before this point.
        if window == 10:
            result = db.check_early_buy_pressure_formation(token_address)
            if result.get("formation_met") and not result.get("already_notified"):
                _fire_formation_alert(token_address, token_row, current_data, elapsed_minutes)


def _fire_formation_alert(token_address, token_row, current_data, elapsed_minutes):
    """Fires the real (and only) alert once formation is confirmed at 10m."""
    symbol = token_row.get("symbol", "???") if token_row else "???"
    name = token_row.get("name", "Unknown") if token_row else "Unknown"

    latest_score = db.get_latest_score(token_address)
    final_score = latest_score.get("final_score", 0) if latest_score else 0

    # Same shape telegram_bot.format_alert() expects, so the message
    # renders identically to a normal alert (DexScreener/Birdeye links,
    # age, price, buys/sells, volume, liquidity, MC).
    alert_data = {
        "tier": 1,
        "formation_confirmed": True,
        "token_address": token_address,
        "symbol": symbol,
        "name": name,
        "price_usd": current_data.get("price_usd", 0),
        "market_cap_usd": current_data.get("market_cap_usd", 0),
        "liquidity_usd": current_data.get("liquidity_usd", 0),
        "volume_5m": current_data.get("volume_5m", 0),
        "buys_5m": current_data.get("buys_5m", 0),
        "sells_5m": current_data.get("sells_5m", 0),
        "age_minutes": elapsed_minutes,
    }

    print(
        f"  🔥 FORMATION CONFIRMED: {token_address[:8]}... "
        f"${symbol} — firing alert"
    )

    try:
        message_id = send_alert(alert_data)
        alert_id = db.add_alert(
            token_address=token_address,
            tier=1,
            final_score=final_score,
            price_at_alert=alert_data["price_usd"],
            market_cap_at_alert=alert_data["market_cap_usd"],
            message_id=str(message_id) if message_id else None,
        )
        db.add_outcome(alert_id, token_address, alert_data["price_usd"])
        db.mark_formation_notified(token_address, window_minutes=10)
    except Exception as e:
        if DEBUG_MODE:
            print(f"  ⚠️ formation alert send error: {e}")
