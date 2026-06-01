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

_last_update_id = 0


def send_message(text, silent=False):
    if not TELEGRAM_ENABLED:
        return None
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
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
            print("Telegram send error: " + str(e))
        return None


def get_updates(offset=None):
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
    global _last_update_id
    if not TELEGRAM_ENABLED:
        return
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
    t = threading.Thread(target=command_listener, daemon=True)
    t.start()


def get_age_label(created_at):
    if not created_at:
        return "Unknown", "⚪"
    ts = created_at / 1000 if created_at > 1e10 else created_at
    mins = (time.time() - ts) / 60
    if mins < 0 or mins > 10000:
        return "Unknown", "⚪"
    if mins < 5:
        return str(int(mins)) + "m", "🟢"
    elif mins < 15:
        return str(int(mins)) + "m", "🟡"
    else:
        return str(int(mins)) + "m", "🔴"


def format_alert(alert_data):
    addr = alert_data["token_address"]
    symbol = alert_data.get("symbol", "???")
    name = alert_data.get("name", "")
    mc = alert_data.get("market_cap_usd", 0)
    liq = alert_data.get("liquidity_usd", 0)
    vol5m = alert_data.get("volume_5m", 0)
    buys = alert_data.get("buys_5m", 0)
    sells = alert_data.get("sells_5m", 0)
    price = alert_data.get("price_usd", 0)
    created_at = alert_data.get("created_at") or alert_data.get("pair_created_at")

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
    return "\n".join(parts)


def format_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed):
    fire = "💎" * min(int(multiplier), 5)
    if minutes_elapsed < 60:
        time_str = str(int(minutes_elapsed)) + "m"
    else:
        time_str = str(round(minutes_elapsed / 60, 1)) + "h"
    msg = (
        fire + " <b>" + str(int(multiplier)) + "x</b>\n"
        "<b>$" + symbol + "</b> " + format_number(mc_at_alert) +
        " \u2197\ufe0f " + format_number(mc_now) + " within " + time_str + "\n"
        "CA: <code>" + addr + "</code>"
    )
    return msg


def send_alert(alert_data):
    tier = alert_data.get("tier", 0)
    if tier == 0:
        return None
    bot_state["alerts_sent"] += 1
    msg = format_alert(alert_data)
    return send_message(msg, silent=False)


def send_x_alert(symbol, name, addr, multiplier, mc_now, mc_at_alert, minutes_elapsed=0):
    msg = format_x_alert(
        symbol=symbol, name=name, addr=addr,
        multiplier=multiplier, mc_now=mc_now,
        mc_at_alert=mc_at_alert, minutes_elapsed=minutes_elapsed
    )
    return send_message(msg, silent=False)


def send_startup_message():
    msg = (
        "🤖 <b>Solana Signal Bot Online</b>\n"
        "Scanning Pump.fun for early opportunities...\n"
        "Send /help for commands."
    )
    return send_message(msg)
￼Enter
