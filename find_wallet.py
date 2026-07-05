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
    day = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
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

        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ HTTP {resp.status_code} on page {page}, stopping pagination")
                break
            batch = resp.json()
        except Exception as e:
            print(f"⚠️ request error on page {page}: {e}")
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


def score_candidates(wallets, target_ratio, target_duration_hours, ratio_tolerance=0.35, duration_tolerance_hours=6):
    """
    Scores each wallet that has both buys and sells against the known
    trade's price ratio and hold duration. Returns sorted candidates,
    closest match first.
    """
    candidates = []

    for addr, data in wallets.items():
        buys, sells = data["buys"], data["sells"]
        if not buys or not sells:
            continue

        total_sol_in = sum(b["sol"] for b in buys)
        total_tokens_bought = sum(b["tokens"] for b in buys)
        total_sol_out = sum(s["sol"] for s in sells)
        total_tokens_sold = sum(s["tokens"] for s in sells)

        if total_tokens_bought <= 0 or total_tokens_sold <= 0:
            continue

        avg_buy_price = total_sol_in / total_tokens_bought
        avg_sell_price = total_sol_out / total_tokens_sold
        if avg_buy_price <= 0:
            continue

        ratio = avg_sell_price / avg_buy_price

        first_buy_ts = min(b["ts"] for b in buys)
        last_sell_ts = max(s["ts"] for s in sells)
        duration_hours = (last_sell_ts - first_buy_ts) / 3600 if last_sell_ts > first_buy_ts else None

        ratio_diff = abs(ratio - target_ratio) / target_ratio
        if ratio_diff > ratio_tolerance:
            continue

        duration_diff = None
        if duration_hours is not None:
            duration_diff = abs(duration_hours - target_duration_hours)
            if duration_diff > duration_tolerance_hours:
                continue

        candidates.append({
            "wallet": addr,
            "ratio": ratio,
            "ratio_diff_pct": ratio_diff * 100,
            "duration_hours": duration_hours,
            "total_sol_in": total_sol_in,
            "total_sol_out": total_sol_out,
            "num_buys": len(buys),
            "num_sells": len(sells),
            "_buys": buys,
            "_sells": sells,
        })

    candidates.sort(key=lambda c: c["ratio_diff_pct"])
    return candidates


def compute_usd_figures(candidate):
    """
    Fills in real dollar in/out for one candidate using the actual SOL
    price at each individual buy/sell timestamp — not today's price,
    since this trade may span days where SOL moved. Only call this on
    the small shortlist that actually gets printed, not every wallet.
    """
    usd_in = 0.0
    usd_out = 0.0
    missing_price = False

    for b in candidate["_buys"]:
        price = get_historical_sol_price(b["ts"])
        if price is None:
            missing_price = True
            continue
        usd_in += b["sol"] * price

    for s in candidate["_sells"]:
        price = get_historical_sol_price(s["ts"])
        if price is None:
            missing_price = True
            continue
        usd_out += s["sol"] * price

    candidate["usd_in"] = usd_in
    candidate["usd_out"] = usd_out
    candidate["usd_price_incomplete"] = missing_price
    return candidate


def main():
    parser = argparse.ArgumentParser(description="Find a wallet from known entry/exit trade data")
    parser.add_argument("mint", help="Token mint address")
    parser.add_argument("--entry-price", type=float, required=True, help="Known avg entry price (SOL or USD per token, unit doesn't matter as long as consistent with --exit-price)")
    parser.add_argument("--exit-price", type=float, required=True, help="Known avg exit price")
    parser.add_argument("--duration-hours", type=float, default=None, help="Known hold duration in hours (e.g. 1d5h26m = 29.43)")
    parser.add_argument("--max-pages", type=int, default=60, help="Max Helius pages to fetch (100 txs/page)")
    args = parser.parse_args()

    target_ratio = args.exit_price / args.entry_price
    print(f"Target ratio: {target_ratio:.2f}x")
    if args.duration_hours:
        print(f"Target duration: {args.duration_hours:.2f}h")

    print(f"\nFetching swap history for {args.mint} ...")
    txs = fetch_all_swaps(args.mint, max_pages=args.max_pages)
    print(f"\nTotal transactions fetched: {len(txs)}")

    wallets = parse_wallet_trades(txs, args.mint)
    print(f"Wallets with any buy/sell activity: {len(wallets)}")

    candidates = score_candidates(
        wallets,
        target_ratio,
        args.duration_hours or 999999,  # effectively no duration filter if not given
    )

    if not candidates:
        print("\n❌ No wallet matched within tolerance. Showing the 5 closest misses instead (ignoring tolerance) so you can see how close it got:\n")
        loose = score_candidates(
            wallets, target_ratio, args.duration_hours or 999999,
            ratio_tolerance=999, duration_tolerance_hours=999999,
        )
        for c in loose[:5]:
            compute_usd_figures(c)
            print(f"  Wallet: {c['wallet']}")
            print(f"    Ratio: {c['ratio']:.2f}x (target {target_ratio:.2f}x, off by {c['ratio_diff_pct']:.1f}%)")
            if c["duration_hours"] is not None:
                print(f"    Duration: {c['duration_hours']:.2f}h")
            print(f"    Buys: {c['num_buys']} ({c['total_sol_in']:.2f} SOL in, ~${c['usd_in']:,.2f}) | Sells: {c['num_sells']} ({c['total_sol_out']:.2f} SOL out, ~${c['usd_out']:,.2f})")
            if c["usd_price_incomplete"]:
                print("    ⚠️ some historical prices unavailable — USD figures may be incomplete")
            print()
        if not loose:
            print("  (no wallets had both a buy and a sell at all — history likely doesn't reach far enough back yet, raise --max-pages)")
    else:
        print(f"\n✅ {len(candidates)} candidate(s), closest match first:\n")
        for c in candidates[:10]:
            compute_usd_figures(c)
            print(f"  Wallet: {c['wallet']}")
            print(f"    Ratio: {c['ratio']:.2f}x (target {target_ratio:.2f}x, off by {c['ratio_diff_pct']:.1f}%)")
            if c["duration_hours"] is not None:
                print(f"    Duration: {c['duration_hours']:.2f}h")
            print(f"    Buys: {c['num_buys']} ({c['total_sol_in']:.2f} SOL in, ~${c['usd_in']:,.2f}) | Sells: {c['num_sells']} ({c['total_sol_out']:.2f} SOL out, ~${c['usd_out']:,.2f})")
            if c["usd_price_incomplete"]:
                print("    ⚠️ some historical prices unavailable — USD figures may be incomplete")
            print()

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
