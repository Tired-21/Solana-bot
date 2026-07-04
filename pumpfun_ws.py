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
actually added it to the database, or after MAX_PENDING_ATTEMPTS
fruitless tries (~2 minutes at a 10s scan interval).
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
MAX_PENDING_ATTEMPTS = 12  # ~2 minutes at a 10s scan interval

_incoming = queue.Queue()   # raw creation events straight off the socket
_pending = {}                # address -> tracking info, see get_new_tokens()
_pending_lock = threading.Lock()
_started = False


def _handle_message(raw_message):
    try:
        data = json.loads(raw_message)
    except Exception:
        return

    # PumpPortal sends an ack/welcome message on subscribe too — only
    # care about actual token creation events.
    if data.get("txType") != "create" or not data.get("mint"):
        return

    _incoming.put({
        "address": data["mint"],
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "received_at": time.time(),  # the real discovery instant
    })

    if DEBUG_MODE:
        print(f"  🆕 WS launch: {data.get('symbol', '?')} {data['mint'][:8]}...")


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
                    "attempts": 0,
                    "resolved_dex": None,
                }

        ready = []
        stale = []

        for addr, info in list(_pending.items())[:limit]:
            # Already picked up by the main pipeline — the normal
            # active-tokens loop takes over from here.
            if db.get_token(addr):
                stale.append(addr)
                continue

            if info["resolved_dex"] is None:
                info["attempts"] += 1
                current = get_token_data(addr)
                if current:
                    info["resolved_dex"] = current
                elif info["attempts"] >= MAX_PENDING_ATTEMPTS:
                    if DEBUG_MODE:
                        print(f"  ⌛ Giving up on {addr[:8]}... — never indexed by DexScreener")
                    stale.append(addr)
                    continue
                else:
                    continue  # keep waiting for DexScreener to index it

            current = info["resolved_dex"]
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
