"""
telegram_bot.py - Telegram Message Sender + Command Handler
"""

import requests
import threading
import time
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED,
    TELEGRAM_SETTINGS, ALERT_THRESHOLDS, DEBUG_MODE
)
from helpers import format_number, format_price

# Global bot state
bot_state = {
    "scanning": True,
    "last_scan": 0,
    "tokens_tracked": 0,
    "alerts_sent": 0,
}

# Track last processed update ID to avoid repeats
_last_update_id = 0


def send_message(text, silent=False):
    """Sends a message to Telegram."""
    if not TELEGRAM_ENABLED:
        if DEBUG_MODE:
            print(f"[TELEGRAM DISABLED] Would send:\n{text[:200]}...")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": TELEGRAM_SETTINGS.get("parse_mode", "HTML"),
        "disable_web_page_preview": TELEGRAM_SETTINGS.get("disable_preview", True),
        "disable_notification": silent
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("ok"):
            return data.get("result", {}).get("message_id")
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Telegram send error: {e}")
        return None


def get_updates(offset=None):
    """Polls Telegram for new messages/commands."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 10, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception:
        pass
    return []


def handle_command(command):
    """Handles a bot command."""
    global bot_state

    if command == "/stop":
        bot_state["scanning"] = False
        send_message("🛑 <b>Bot paused.</b>\nSend /start to resume scanning.")

    elif command == "/start":
        bot_state["scanning"] = True
        send_message("✅ <b>Bot resumed.</b>\nScanning for tokens...")

    elif command == "/status":
        state = "🟢 Scanning" if bot_state["scanning"] else "🔴 Paused"
        last = bot_state.get("last_scan", 0)
        last_str = f"{int((time.time() - last) / 60)}m ago" if last else "Never"
        msg = (
            f"📊 <b>Bot Status</b>\n"
            f"State: {state}\n"
            f"Tokens tracked: {bot_state['tokens_tracked']}\n"
            f"Alerts sent: {bot_state['alerts_sent']}\n"
            f"Last scan: {last_str}"
        )
        send_message(msg)

    elif command == "/help":
        send_message(
            "🤖 <b>Commands</b>\n"
            "/start — resume scanning\n"
            "/stop — pause scanning\n"
            "/status — show bot status\n"
            "/help — show this message"
        )


def command_listener():
    """Background thread that polls for commands."""
    global _last_update_id
    if not TELEGRAM_ENABLED:
        return

    if DEBUG_MODE:
        print("🎧 Command listener started")

    while True:
        try:
            updates = get_updates(offset=_last_update_id + 1 if _last_update_id else None)
            for update in updates:
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # Only accept commands from your own chat
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                if text.startswith("/"):
                    cmd = text.split()[0].lower()
                    handle_command(cmd)

        except Exception as e:
            if DEBUG_MODE:
                print(f"❌ Command listener error: {e}")

        time.sleep(3)


def start_command_listener():
    """Starts the command listener in a background thread."""
    t = threading.Thread(target=command_listener, daemon=True)
    t.start()


def format_alert(alert_data):
    """Formats clean signal alert."""
    addr = alert_data["token_address"]
    symbol = alert_data.get("symbol", "???")
    name = alert_data.get("name", "")
    mc = alert_data.get("market_cap_usd", 0)
    liq = alert_data.get("liquidity_usd", 0)
    vol5m = alert_data.get("volume_5m", 0)
    buys = alert_data.get("buys_5m", 0)
    sells = alert_data.get("sells_5m", 0)
    price = alert_data.get("price_usd", 0)

    dex_link = f"https://dexscreener.com/solana/{addr}"
    birdeye_link = f"https://birdeye.so/token/{addr}?chain=solana"

    msg = f"""💎🧚🏽‍♀️ <b>New Alert</b>
<b>{name} (${symbol})</b>
Price: {format_price(price)}
Buys (5m): {buys} | Sells (5m): {sells}
Volume (5m): {format_number(vol5m)}
Liquidity: {format_number(liq)}
MC: {format_number(mc)}
CA: <code>{addr}</code>
🔗 <a href="{dex_link}">DexScreener</a> | 🔗 <a href="{birdeye_link}">Birdeye</a>"""

    return msg


def format_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed):
    """Formats a 2x/5x/10x tracking alert."""
    fire_count = min(int(multiplier), 5)
    fire = "💎" * fire_count

    if minutes_elapsed < 60:
        time_str = f"{minutes_elapsed:.0f}m"
    else:
        hours = minutes_elapsed / 60
        time_str = f"{hours:.1f}h"

    msg = f"""{fire} <b>{multiplier:.0f}x</b>
<b>${symbol}</b> {format_number(mc_at_alert)} ↗️ {format_number(mc_now)} within {time_str}
CA: <code>{addr}</code>"""

    return msg


def send_alert(alert_data):
    """Sends a clean signal alert."""
    tier = alert_data.get("tier", 0)
    if tier == 0:
        return None
    bot_state["alerts_sent"] += 1
    msg = format_alert(alert_data)
    return send_message(msg, silent=False)


def send_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed=0):
    """Sends a 2x/5x/10x update alert."""
    msg = format_x_alert(
        symbol=symbol, name=name, addr=addr,
        multiplier=multiplier, mc_now=mc_now,
        mc_at_alert=mc_at_alert, minutes_elapsed=minutes_elapsed
    )
    return send_message(msg, silent=False)


def send_startup_message():
    """Sends a startup message."""
    msg = (
        "🤖 <b>Solana Signal Bot Online</b>\n"
        "Scanning Pump.fun for early opportunities...\n"
        "Send /help for commands."
    )
    return send_message(msg)


def send_test_message():
    """Sends a test message."""
    return send_message("✅ <b>Bot connected.</b>\nTelegram is working!")


if __name__ == "__main__":
    print("Testing telegram_bot.py...")
    result = send_test_message()
    if result:
        print(f"✅ Message sent! ID: {result}")
    else:
        print("❌ Failed")
