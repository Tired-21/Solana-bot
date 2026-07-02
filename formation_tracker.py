"""
formation_tracker.py - Formation Window Tracker
================================================
Tracks alerted tokens at fixed post-alert intervals (1m, 5m, 10m, 15m,
30m, 60m), recording FDV, volume, holder count, buy/sell counts, and
migration status at each checkpoint.

This is the infrastructure for Ola's validated "Early Buy Pressure"
formation: 10m volume >= $40k + 10m return >= 2.5x + 10m holder count
>= 250 + migration <= 20m = 6.13x lift over baseline, 222 matches.

Called from main.py's scan loop for every alerted token.
"""

import time
from config import DEBUG_MODE
import database as db
from telegram_bot import send_message

FORMATION_WINDOWS = [1, 5, 10, 15, 30, 60]  # minutes post-alert


def update_formation_windows(token_address, alert_timestamp, current_data):
    """
    For a given alerted token, checks which formation windows have elapsed
    since the alert, and records any that haven't been captured yet.

    Called every scan cycle for all alerted tokens.
    current_data: the token's latest DexScreener snapshot.
    """
    if not alert_timestamp or not current_data:
        return

    now = time.time()
    elapsed_minutes = (now - alert_timestamp) / 60

    alert_fdv = current_data.get("alert_fdv_usd") or current_data.get("market_cap_usd", 0) or 0
    if not alert_fdv:
        return

    # Determine migration status from dex_id
    dex_id = current_data.get("dex_id", "") or ""
    is_migrated = "raydium" in dex_id.lower()
    minutes_to_migration = None

    if is_migrated:
        existing = db.get_formation_windows(token_address)
        for w in existing:
            if w.get("is_migrated") and w.get("minutes_to_migration") is not None:
                minutes_to_migration = w["minutes_to_migration"]
                break
        if minutes_to_migration is None:
            minutes_to_migration = round(elapsed_minutes, 2)

    already_recorded = {
        w["window_minutes"] for w in db.get_formation_windows(token_address)
    }

    for window in FORMATION_WINDOWS:
        if window > elapsed_minutes:
            continue
        if window in already_recorded:
            continue

        current_fdv = current_data.get("market_cap_usd", 0) or 0
        fdv_return = (current_fdv / alert_fdv) if alert_fdv > 0 else 0

        db.add_formation_window(
            token_address=token_address,
            alert_timestamp=int(alert_timestamp),
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

        # At 10m check for Ola's Early Buy Pressure formation
        if window == 10:
            result = db.check_early_buy_pressure_formation(token_address)
            if result.get("formation_met"):
                print(
                    f"  🔥 EARLY BUY PRESSURE FORMATION: {token_address[:8]}... "
                    f"Vol ${result['volume_usd']:,.0f} | "
                    f"Return {result['fdv_return']:.2f}x | "
                    f"Holders {result['holder_count']}"
                )

                # Send Telegram follow-up alert — only once per token
                if not result.get("already_notified"):
                    token_row = db.get_token(token_address)
                    symbol = token_row.get("symbol", "???") if token_row else "???"

                    msg = (
                        f"🔥 FORMATION CONFIRMED: ${symbol}\n\n"
                        f"Early Buy Pressure validated at 10m:\n"
                        f"📊 Volume: ${result['volume_usd']:,.0f}\n"
                        f"📈 Return: {result['fdv_return']:.2f}x\n"
                        f"👥 Holders: {result['holder_count']}\n\n"
                        f"CA: {token_address}"
                    )
                    try:
                        send_message(msg)
                        db.mark_formation_notified(token_address, window_minutes=10)
                    except Exception as e:
                        if DEBUG_MODE:
                            print(f"  ⚠️ formation alert send error: {e}")
