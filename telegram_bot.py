"""
telegram_bot.py - Telegram Message Sender
Clean signal alerts with X tracking.
"""

import requests
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

_last_update_id = 0


def get_updates(offset=None):
    """Polls Telegram for new messages/commands."""
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/getUpdates"
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
        import time
        state = "🟢 Scanning" if bot_state["scanning"] else "🔴 Paused"
        last = bot_state.get("last_scan", 0)
        last_str = str(int((time.time() - last) / 60)) + "m ago" if last else "Never"
        msg = (
            "<b>Bot Status</b>\n"
            "State: " + state + "\n"
            "Tokens tracked: " + str(bot_state["tokens_tracked"]) + "\n"
            "Alerts sent: " + str(bot_state["alerts_sent"]) + "\n"
            "Last scan: " + last_str
        )
        send_message(msg)
    elif command == "/help":
        send_message(
            "<b>Commands</b>\n"
            "/start - resume scanning\n"
            "/stop - pause scanning\n"
            "/status - show bot status\n"
            "/help - show this message"
        )


def command_listener():
    """Background thread that polls for commands."""
    global _last_update_id
    if not TELEGRAM_ENABLED:
        return
    import time
    while True:
        try:
            updates = get_updates(offset=_last_update_id + 1 if _last_update_id else None)
            for update in updates:
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue
                if text.startswith("/"):
                    cmd = text.split()[0].lower()
                    handle_command(cmd)
        except Exception:
            pass
        time.sleep(3)


def start_command_listener():
    """Starts the command listener in a background thread."""
    import threading
    t = threading.Thread(target=command_listener, daemon=True)
    t.start()



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
        else:
            if DEBUG_MODE:
                print(f"❌ Telegram error: {data}")
            return None

    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Telegram send error: {e}")
        return None


def get_age_label(created_at):
    """Returns age string and emoji."""
    if not created_at:
        return "Unknown", "⚪"
    import time
    mins = (time.time() - created_at / 1000) / 60
    if mins < 5:
        return str(int(mins)) + "m", "🟢"
    elif mins < 15:
        return str(int(mins)) + "m", "🟡"
    else:
        return str(int(mins)) + "m", "🔴"


def format_alert(alert_data):
    """Formats clean signal alert - no tier labels."""
    addr = alert_data["token_address"]
    symbol = alert_data.get("symbol", "???")
    name = alert_data.get("name", "")
    mc = alert_data.get("market_cap_usd", 0)
    liq = alert_data.get("liquidity_usd", 0)
    vol5m = alert_data.get("volume_5m", 0)
    buys = alert_data.get("buys_5m", 0)
    sells = alert_data.get("sells_5m", 0)
    price = alert_data.get("price_usd", 0)
    created_at = alert_data.get("created_at")

    age_str, age_emoji = get_age_label(created_at)
    dex_link = "https://dexscreener.com/solana/" + addr
    birdeye_link = "https://birdeye.so/token/" + addr + "?chain=solana"

    parts = []
    parts.append("<b>" + name + " ($" + symbol + ")</b>")
    parts.append("Age: " + age_str + " " + age_emoji)
    parts.append("Price: " + format_price(price))
    parts.append("Buys (5m): " + str(buys) + " | Sells (5m): " + str(sells))
    parts.append("Volume (5m): " + format_number(vol5m))
    parts.append("Liquidity: " + format_number(liq))
    parts.append("MC: " + format_number(mc))
    parts.append("CA: <code>" + addr + "</code>")
    parts.append('<a href="' + dex_link + '">DexScreener</a> | <a href="' + birdeye_link + '">Birdeye</a>')
    msg = "\n".join(parts)
    return msg


def format_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed):
    """Formats a 2x/5x/10x tracking alert."""
    fire_count = min(int(multiplier), 5)
    fire = "💎" * fire_count

    # Format time elapsed
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

    msg = format_alert(alert_data)
    return send_message(msg, silent=False)


def send_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed=0):
    """Sends a 2x/5x/10x update alert."""
    msg = format_x_alert(
        symbol=symbol,
        name=name,
        addr=addr,
        multiplier=multiplier,
        mc_now=mc_now,
        mc_at_alert=mc_at_alert,
        minutes_elapsed=minutes_elapsed
    )
    return send_message(msg, silent=False)


def send_startup_message():
    """Sends a startup message."""
    msg = "🤖 <b>Solana Signal Bot Online</b>\nScanning Pump.fun for early opportunities..."
    return send_message(msg)


def send_test_message():
    """Sends a test message."""
    msg = "✅ <b>Bot connected.</b>\nTelegram is working!"
    return send_message(msg)


if __name__ == "__main__":
    print("Testing telegram_bot.py...")

    result = send_test_message()
    if result:
        print(f"✅ Message sent! ID: {result}")
    else:
        print("❌ Failed")

    # Preview
    mock_alert = {
        "token_address": "7pwmwCfPK1o959SX3QQgLABmMEi2pndjmu7fB219pump",
        "symbol": "Erdős",
        "name": "The Erdős Breakthrough",
        "tier": 1,
        "final_score": 58,
        "price_usd": 0.000062,
        "market_cap_usd": 60970,
        "liquidity_usd": 19600,
        "volume_5m": 17350,
        "buys_5m": 167,
        "sells_5m": 114,
    }

    print("\nAlert Preview:")
    print("-" * 40)
    print(format_alert(mock_alert))

    print("\nX Alert Preview:")
    print("-" * 40)
    print(format_x_alert(
        symbol="Erdős",
        name="The Erdős Breakthrough",
        addr="7pwmwCfPK1o959SX3QQgLABmMEi2pndjmu7fB219pump",
        multiplier=3,
        mc_now=99000,
        mc_at_alert=33000,
        minutes_elapsed=47
    ))

    print("\n✅ telegram_bot.py done!")
