"""
pumpfun_ws.py - Real-time pump.fun launch feed (PumpPortal WebSocket)
=======================================================================
Replaces the DexScreener-indexing-lag discovery path with PumpPortal's
free WebSocket, which pushes a message the instant a token is created
on pump.fun's bonding curve — wss://pumpportal.fun/api/data, method
"subscribeNewToken" (free, no API key required for this stream).

Why this exists: the old "pumpfun.py" never actually talked to
pump.fun — it polled DexScreener's token-profiles/latest endpoint,
which only lists a pair once it's seen real trading activity. helius.py
already documented a confirmed 74+ minute gap between that discovery
and the token's true on-chain mint time. This module fixes that by
timestamping tokens the moment this bot observes their creation event,
independent of when DexScreener gets around to indexing them.

Runs in a background daemon thread (asyncio loop) so it doesn't block
main.py's synchronous scan loop. Reconnects automatically on drop.

Newly-seen mints are held in a small pending pool and matched against
DexScreener (for liquidity/MC) on each get_new_tokens() call, since a
brand new bonding-curve pair sometimes takes a few seconds to a minute
to appear there. A token is dropped from the pool once main.py has
actually added it to the database, or after STALE_AFTER_SECONDS of not
making it in.
"""

import asyncio
import json
import queue
import threading
import time

import websockets

from config import DEBUG_MODE
from dexscreener import get_token_data
import database as db

PUMPPORTAL_WS_URL = "wss://pumpportal.fun/api/data"

_incoming = queue.Queue()   # raw creation events straight off the socket
_pending = {}                # address -> tracking info, see get_new_tokens()
_pending_lock = threading.Lock()
_started = False


# Established mints that have shown up leaking through the "create" event
# stream even though they're obviously not new pump.fun launches (e.g. USDC's
# real mint appearing as a repeated fake "create"). Hard-excluded on sight.
KNOWN_NON_LAUNCH_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "So11111111111111111111111111111111111111112",  # wrapped SOL
}


def _handle_message(raw_message):
    try:
        data = json.loads(raw_message)
    except Exception:
        return

    # PumpPortal sends an ack/welcome message on subscribe too — only
    # care about actual token creation events.
    if data.get("txType") != "create" or not data.get("mint"):
        return

    mint = data["mint"]
    if mint in KNOWN_NON_LAUNCH_MINTS:
        return

    # A genuine pump.fun create event always carries bonding-curve fields.
    # Anything claiming to be a "create" without them isn't one — reject
    # rather than let it burn a DexScreener lookup for nothing.
    if "bondingCurveKey" not in data and "vSolInBondingCurve" not in data:
        return

    _incoming.put({
        "address": mint,
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "received_at": time.time(),  # the real discovery instant
    })

    if DEBUG_MODE:
        print(f"  🆕 WS launch: {data.get('symbol', '?')} {mint[:8]}...")


async def _listen():
    while True:
        try:
            async with websockets.connect(
                PUMPPORTAL_WS_URL, ping_interval=30, ping_timeout=10
            ) as ws:
                if DEBUG_MODE:
                    print("  🔌 PumpPortal WS connected — subscribing to new token feed")
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                async for message in ws:
                    _handle_message(message)
        except Exception as e:
            if DEBUG_MODE:
                print(f"  ⚠️ PumpPortal WS disconnected: {e} — reconnecting in 5s")
            await asyncio.sleep(5)


def _thread_target():
    while True:
        try:
            asyncio.run(_listen())
        except Exception as e:
            if DEBUG_MODE:
                print(f"  ⚠️ PumpPortal WS thread crashed, restarting: {e}")
            time.sleep(5)


def start_listener():
    """Starts the background WS thread once. Safe to call more than once."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()
    if DEBUG_MODE:
        print("  🎧 PumpPortal WS listener started")


STALE_AFTER_SECONDS = 180  # give up if not added to the DB within 3 minutes of WS sighting


def get_new_tokens(limit=50):
    """
    Drains newly-created tokens from the WS feed and resolves each one
    against DexScreener for liquidity/MC data (the WS event alone
    doesn't carry reliable liquidity numbers this early).

    Returns the same shape main.py's discover_new_tokens() already
    expects, except created_timestamp is the real moment this bot saw
    the mint event (ms since epoch) — not DexScreener's laggy guess.
    """
    with _pending_lock:
        while not _incoming.empty():
            item = _incoming.get()
            addr = item["address"]
            if addr not in _pending:
                _pending[addr] = {
                    "first_seen": item["received_at"],
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                }

        ready = []
        stale = []
        now = time.time()

        for addr, info in list(_pending.items())[:limit]:
            # Already picked up by the main pipeline — the normal
            # active-tokens loop takes over from here.
            if db.get_token(addr):
                stale.append(addr)
                continue

            if now - info["first_seen"] > STALE_AFTER_SECONDS:
                if DEBUG_MODE:
                    print(f"    ⌛ Giving up on {addr[:8]}... — not added within {STALE_AFTER_SECONDS}s of WS sighting")
                stale.append(addr)
                continue

            # Always fetch fresh — a token rejected for low MC/liquidity
            # last cycle may well clear the bar by this one. Caching the
            # first DexScreener response permanently was the bug: it
            # meant a rejected token could never re-qualify later.
            current = get_token_data(addr)
            if not current:
                continue  # DexScreener hasn't indexed the pair yet, retry next cycle

            ready.append({
                "address": addr,
                "symbol": current.get("symbol") or info.get("symbol"),
                "name": current.get("name") or info.get("name"),
                "creator": None,
                "created_timestamp": int(info["first_seen"] * 1000),
                "market_cap": current.get("market_cap_usd", 0),
                "market_cap_usd": current.get("market_cap_usd", 0),
                "liquidity_usd": current.get("liquidity_usd", 0),
                "is_graduated": False,
                "bonding_curve": current.get("pair_address"),
            })

        for addr in stale:
            del _pending[addr]

    return ready
