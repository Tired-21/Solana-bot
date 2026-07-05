"""
find_wallet.py - Identify a wallet from a known trade's entry/exit prices
===========================================================================
Standalone forensic script. Not part of the live bot's scan loop — run it
manually with a token mint address and the trade details you already know
(from a shared BonkBot PnL card, for example) and it walks the token's
full on-chain swap history via Helius to find which wallet's actual buys
and sells match.

Why this works without needing the wallet address up front: pump.fun
tokens have a fixed 1,000,000,000 token supply, so "$5K @ 0.000005" and
"$363K @ 0.000363" are both just price * 1e9 — meaning the entry/exit
*ratio* (0.000363 / 0.000005 ≈ 72.6x) is a currency-independent fact
about the trade. That ratio must show up in raw SOL terms too, so we
don't need any USD/SOL conversion to match on it — just find the wallet
whose (avg SOL received per token sold) / (avg SOL spent per token
bought) lands near that same ratio, over roughly the same hold duration.

Usage:
    python find_wallet.py <mint_address> --entry-price 0.000005 --exit-price 0.000363 --duration-hours 29.4

Costs Helius API credits — pulls full swap history for the mint, which
for a token that ran 72x over a day+ could be several thousand
transactions. Uses the same rate limiter as the rest of the bot.
"""

import argparse
import sys
import time
import datetime

import requests

from config import HELIUS_API, HELIUS_API_KEY, DEBUG_MODE
from rate_limiter import wait_for

_price_cache = {}


def get_historical_sol_price(ts):
    """
    Approx SOL/USD price near a given unix timestamp, via CoinGecko's
    free historical range endpoint (no API key needed). Cached per
    calendar day — day-level precision is plenty for "how much did this
    wallet actually put in / take out in dollars", and it keeps calls
    well under CoinGecko's free-tier rate limit even across a wallet
    with many buys/sells spread over several days.
    """
    day = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
    if day in _price_cache:
        return _price_cache[day]

    url = "https://api.coingecko.com/api/v3/coins/solana/market_chart/range"
    params = {"vs_currency": "usd", "from": ts - 3600, "to": ts + 3600}
    try:
        time.sleep(1.5)  # stay well under CoinGecko's free rate limit
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        prices = data.get("prices", [])
        if not prices:
            _price_cache[day] = None
            return None
        closest = min(prices, key=lambda p: abs(p[0] / 1000 - ts))
        _price_cache[day] = closest[1]
        return closest[1]
    except Exception as e:
        print(f"  ⚠️ historical price lookup failed for {day}: {e}")
        _price_cache[day] = None
        return None


def fetch_all_swaps(mint_address, max_pages=60, page_limit=100):
    """
    Walks the full enhanced-transaction history for a mint, paginating
    backward via `before` signature cursor. Returns raw Helius tx dicts,
    swap-type only (skips non-swap activity like transfers/approvals).
    """
    if not HELIUS_API_KEY:
        print("❌ HELIUS_API_KEY not set — can't query Helius.")
        return []

    all_txs = []
    before_sig = None

    for page in range(max_pages):
        wait_for("helius")
        url = f"{HELIUS_API}/addresses/{mint_address}/transactions"
        params = {"api-key": HELIUS_API_KEY, "limit": page_limit}
        if before_sig:
            params["before"] = before_sig

        batch = None
        backoff = 5
        for retry in range(6):  # up to ~5+10+20+40+60+60 = ~195s of backoff before giving up on this page
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    print(f"  ⏳ rate limited (429) on page {page}, backing off {backoff}s (retry {retry + 1}/6)")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                if resp.status_code != 200:
                    print(f"⚠️ HTTP {resp.status_code} on page {page}, stopping pagination")
                    batch = None
                    break
                batch = resp.json()
                break
            except Exception as e:
                print(f"⚠️ request error on page {page}: {e}")
                batch = None
                break

        if batch is None:
            print(f"  giving up after repeated failures on page {page} — using what's fetched so far ({len(all_txs)} txs)")
            break

        if not isinstance(batch, list) or not batch:
            break

        all_txs.extend(batch)
        before_sig = batch[-1].get("signature")
        if not before_sig:
            break

        print(f"  fetched page {page + 1} ({len(batch)} txs, {len(all_txs)} total)")

        if len(batch) < page_limit:
            break  # last page

    return all_txs


def parse_wallet_trades(txs, mint_address):
    """
    Groups swaps by wallet (feePayer), separating buys (mint appears in
    tokenOutputs — they received the token) from sells (mint appears in
    tokenInputs — they gave up the token).

    Returns {wallet: {"buys": [...], "sells": [...]}}
    """
    wallets = {}

    for tx in txs:
        signer = tx.get("feePayer", "")
        ts = tx.get("timestamp") or 0
        events = tx.get("events", {})
        swap = events.get("swap", {}) if isinstance(events, dict) else {}
        if not signer or not swap:
            continue

        token_out = swap.get("tokenOutputs", []) or []
        token_in = swap.get("tokenInputs", []) or []
        native_in = swap.get("nativeInput") or {}
        native_out = swap.get("nativeOutput") or {}

        wallet = wallets.setdefault(signer, {"buys": [], "sells": []})

        # Buy: wallet received the target mint, paid SOL
        bought = next((t for t in token_out if t.get("mint") == mint_address), None)
        if bought and native_in.get("amount"):
            sol_spent = float(native_in["amount"]) / 1e9
            tokens_received = float(bought.get("rawTokenAmount", {}).get("tokenAmount", 0) or bought.get("tokenAmount", 0) or 0)
            if tokens_received > 0:
                wallet["buys"].append({"ts": ts, "sol": sol_spent, "tokens": tokens_received})

        # Sell: wallet gave up the target mint, received SOL
        sold = next((t for t in token_in if t.get("mint") == mint_address), None)
        if sold and native_out.get("amount"):
            sol_received = float(native_out["amount"]) / 1e9
            tokens_sold = float(sold.get("rawTokenAmount", {}).get("tokenAmount", 0) or sold.get("tokenAmount", 0) or 0)
            if tokens_sold > 0:
                wallet["sells"].append({"ts": ts, "sol": sol_received, "tokens": tokens_sold})

    return wallets


def score_candidates(wallets, target_entry_price, target_exit_price, target_duration_hours,
                      price_tolerance=0.4, duration_tolerance_hours=6, min_sol_in=0.5):
    """
    Scores each wallet against the known trade's ABSOLUTE entry and exit
    price (in USD), not just their ratio — a dust wallet trading at a
    totally different price range can fake a matching ratio by chance,
    but can't fake matching both absolute numbers at once.

    Converts each wallet's SOL-denominated fills to USD using the real
    historical SOL price at each individual buy/sell timestamp (cached
    per calendar day), since this trade can span days where SOL itself
    moved — a single blended rate would skew the comparison.
    """
    target_ratio = target_exit_price / target_entry_price
    candidates = []

    for addr, data in wallets.items():
        buys, sells = data["buys"], data["sells"]
        if not buys or not sells:
            continue

        total_sol_in = sum(b["sol"] for b in buys)
        total_sol_out = sum(s["sol"] for s in sells)
        if total_sol_in < min_sol_in:
            continue  # dust — see docstring

        usd_in, tokens_in = 0.0, 0.0
        for b in buys:
            price = get_historical_sol_price(b["ts"])
            if price is None:
                continue
            usd_in += b["sol"] * price
            tokens_in += b["tokens"]

        usd_out, tokens_out = 0.0, 0.0
        for s in sells:
            price = get_historical_sol_price(s["ts"])
            if price is None:
                continue
            usd_out += s["sol"] * price
            tokens_out += s["tokens"]

        if tokens_in <= 0 or tokens_out <= 0:
            continue

        avg_entry_price = usd_in / tokens_in
        avg_exit_price = usd_out / tokens_out
        if avg_entry_price <= 0:
            continue

        entry_diff = abs(avg_entry_price - target_entry_price) / target_entry_price
        exit_diff = abs(avg_exit_price - target_exit_price) / target_exit_price
        if entry_diff > price_tolerance or exit_diff > price_tolerance:
            continue

        ratio = avg_exit_price / avg_entry_price
        ratio_diff = abs(ratio - target_ratio) / target_ratio

        first_buy_ts = min(b["ts"] for b in buys)
        last_sell_ts = max(s["ts"] for s in sells)
        duration_hours = (last_sell_ts - first_buy_ts) / 3600 if last_sell_ts > first_buy_ts else None
        if duration_hours is not None and abs(duration_hours - target_duration_hours) > duration_tolerance_hours:
            continue

        candidates.append({
            "wallet": addr,
            "avg_entry_price": avg_entry_price,
            "avg_exit_price": avg_exit_price,
            "entry_diff_pct": entry_diff * 100,
            "exit_diff_pct": exit_diff * 100,
            "ratio": ratio,
            "ratio_diff_pct": ratio_diff * 100,
            "duration_hours": duration_hours,
            "total_sol_in": total_sol_in,
            "total_sol_out": total_sol_out,
            "usd_in": usd_in,
            "usd_out": usd_out,
            "num_buys": len(buys),
            "num_sells": len(sells),
        })

    candidates.sort(key=lambda c: c["entry_diff_pct"] + c["exit_diff_pct"])
    return candidates


def main():
    parser = argparse.ArgumentParser(description="Find a wallet from known entry/exit trade data")
    parser.add_argument("mint", help="Token mint address")
    parser.add_argument("--entry-price", type=float, required=True, help="Known avg entry price in USD per token (e.g. 0.000005)")
    parser.add_argument("--exit-price", type=float, required=True, help="Known avg exit price in USD per token")
    parser.add_argument("--duration-hours", type=float, default=None, help="Known hold duration in hours (e.g. 1d5h26m = 29.43)")
    parser.add_argument("--max-pages", type=int, default=60, help="Max Helius pages to fetch (100 txs/page)")
    parser.add_argument("--min-sol-in", type=float, default=0.5, help="Minimum total SOL spent to count as a candidate (filters out dust)")
    parser.add_argument("--price-tolerance", type=float, default=0.4, help="Allowed fractional deviation on entry/exit price (0.4 = within 40%%)")
    args = parser.parse_args()

    target_ratio = args.exit_price / args.entry_price
    print(f"Target entry price: ${args.entry_price:.9f} | Target exit price: ${args.exit_price:.9f} | Target ratio: {target_ratio:.2f}x")
    if args.duration_hours:
        print(f"Target duration: {args.duration_hours:.2f}h")

    print(f"\nFetching swap history for {args.mint} ...")
    txs = fetch_all_swaps(args.mint, max_pages=args.max_pages)
    print(f"\nTotal transactions fetched: {len(txs)}")

    wallets = parse_wallet_trades(txs, args.mint)
    print(f"Wallets with any buy/sell activity: {len(wallets)}")

    def print_candidate(c):
        pct_return = (c["ratio"] - 1) * 100
        print(f"  Wallet: {c['wallet']}")
        print(f"    Entry: ${c['avg_entry_price']:.9f} (target ${args.entry_price:.9f}, off by {c['entry_diff_pct']:.1f}%)")
        print(f"    Exit:  ${c['avg_exit_price']:.9f} (target ${args.exit_price:.9f}, off by {c['exit_diff_pct']:.1f}%)")
        print(f"    Ratio: {c['ratio']:.2f}x  |  Return: +{pct_return:,.2f}%  (target {target_ratio:.2f}x / +{(target_ratio - 1) * 100:,.2f}%)")
        if c["duration_hours"] is not None:
            print(f"    Duration: {c['duration_hours']:.2f}h")
        print(f"    Invested: {c['total_sol_in']:.2f} SOL (~${c['usd_in']:,.2f}) across {c['num_buys']} buy(s) | Received: {c['total_sol_out']:.2f} SOL (~${c['usd_out']:,.2f}) across {c['num_sells']} sell(s)")
        print(f"    Profit: ~${c['usd_out'] - c['usd_in']:,.2f}")
        print()

    candidates = score_candidates(
        wallets, args.entry_price, args.exit_price,
        args.duration_hours or 999999,
        price_tolerance=args.price_tolerance,
        min_sol_in=args.min_sol_in,
    )

    if not candidates:
        print(f"\n❌ No wallet matched within {args.price_tolerance*100:.0f}% price tolerance. Showing the 5 closest misses instead:\n")
        loose = score_candidates(
            wallets, args.entry_price, args.exit_price, 999999,
            price_tolerance=999, duration_tolerance_hours=999999,
            min_sol_in=args.min_sol_in,
        )
        for c in loose[:5]:
            print_candidate(c)
        if not loose:
            print("  (no wallets had both a buy and a sell above the dust threshold — history may not reach far enough back, raise --max-pages, or lower --min-sol-in)")
    else:
        print(f"\n✅ {len(candidates)} candidate(s), closest match first:\n")
        for c in candidates[:10]:
            print_candidate(c)

    # Railway restarts a worker whenever it exits — without this, the
    # script would finish, Railway would immediately re-run it, and it'd
    # re-query Helius from scratch in a loop before you ever get a
    # chance to read this output. Sleep forever instead; revert the
    # Procfile once you've got what you needed from the logs.
    print("Done. Sleeping to avoid a Railway restart loop — revert your Procfile now.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
