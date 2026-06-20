"""
database.py - SQLite Database Operations
========================================
Handles all data storage for the bot.
"""

import os
import sqlite3
import time
from datetime import datetime
from config import DATABASE_FILE, DEBUG_MODE


def get_connection():
    """Returns a database connection."""
    db_dir = os.path.dirname(DATABASE_FILE)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn


def init_database():
    """Creates all tables if they don't exist."""
    conn = get_connection()
    c = conn.cursor()
    
    # Tracked tokens (tokens we're monitoring)
    c.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            address TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            created_at INTEGER,
            first_seen INTEGER,
            liquidity_usd REAL,
            market_cap_usd REAL,
            deployer_address TEXT,
            is_pump_fun INTEGER DEFAULT 0,
            graduated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            last_updated INTEGER
        )
    ''')
    
    # Price/volume snapshots (collected every 30 seconds)
    c.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            timestamp INTEGER,
            price_usd REAL,
            volume_5m REAL,
            volume_1h REAL,
            liquidity_usd REAL,
            market_cap_usd REAL,
            holders INTEGER,
            buys_5m INTEGER,
            sells_5m INTEGER,
            FOREIGN KEY (token_address) REFERENCES tokens(address)
        )
    ''')
    
    # Engine scores (calculated each cycle)
    c.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            timestamp INTEGER,
            discovery_score REAL,
            structural_score REAL,
            timing_score REAL,
            context_score REAL,
            smart_wallet_score REAL,
            final_score REAL,
            timing_grade TEXT,
            FOREIGN KEY (token_address) REFERENCES tokens(address)
        )
    ''')

    # Wallet behavior snapshots — the trend-tracking table. Captures
    # unique buyer count, entropy, and repeat ratio at each scan, so
    # behavior over time (not just one snapshot) becomes queryable.
    c.execute('''
        CREATE TABLE IF NOT EXISTS wallet_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            timestamp INTEGER,
            unique_buyers INTEGER,
            entropy_normalized REAL,
            repeat_wallet_ratio REAL,
            smart_wallet_hits INTEGER,
            whale_hits INTEGER
        )
    ''')
    
    # Alerts sent
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            timestamp INTEGER,
            tier INTEGER,
            final_score REAL,
            price_at_alert REAL,
            market_cap_at_alert REAL,
            message_id TEXT,
            FOREIGN KEY (token_address) REFERENCES tokens(address)
        )
    ''')
    
    # Outcome tracking (what happened after alert)
    c.execute('''
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            token_address TEXT,
            price_at_alert REAL,
            price_5m REAL,
            price_15m REAL,
            price_30m REAL,
            price_1h REAL,
            max_price REAL,
            min_price REAL,
            pnl_5m REAL,
            pnl_15m REAL,
            pnl_30m REAL,
            pnl_1h REAL,
            max_pnl REAL,
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        )
    ''')
    
    # Smart wallets (wallets with good track records)
    c.execute('''
        CREATE TABLE IF NOT EXISTS smart_wallets (
            address TEXT PRIMARY KEY,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0,
            avg_profit REAL DEFAULT 0,
            last_updated INTEGER
        )
    ''')
    
    # Security scan cache (avoid re-scanning)
    c.execute('''
        CREATE TABLE IF NOT EXISTS security_cache (
            token_address TEXT PRIMARY KEY,
            is_honeypot INTEGER,
            has_freeze INTEGER,
            has_mint INTEGER,
            top_holder_pct REAL,
            scanned_at INTEGER
        )
    ''')
    
    # Market context (SOL price, market regime)
    c.execute('''
        CREATE TABLE IF NOT EXISTS market_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            sol_price REAL,
            sol_change_24h REAL,
            market_regime TEXT
        )
    ''')
    
    # Create indexes for faster queries
    c.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_token ON snapshots(token_address)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_time ON snapshots(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_scores_token ON scores(token_address)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_alerts_token ON alerts(token_address)')
    
    conn.commit()
    conn.close()
    
    if DEBUG_MODE:
        print("✅ Database initialized")


# =============================================================================
# TOKEN OPERATIONS
# =============================================================================

def add_token(address, symbol, name, liquidity_usd, market_cap_usd, 
              deployer_address=None, is_pump_fun=False, created_at=None):
    """Adds a new token to track."""
    conn = get_connection()
    c = conn.cursor()
    now = int(time.time())
    
    c.execute('''
        INSERT OR IGNORE INTO tokens 
        (address, symbol, name, created_at, first_seen, liquidity_usd, 
         market_cap_usd, deployer_address, is_pump_fun, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (address, symbol, name, created_at or now, now, liquidity_usd,
          market_cap_usd, deployer_address, int(is_pump_fun), now))
    
    conn.commit()
    conn.close()


def get_token(address):
    """Gets a single token by address."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM tokens WHERE address = ?', (address,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_tokens():
    """Gets all tokens currently being tracked."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM tokens WHERE status = "active"')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_token_status(address, status):
    """Updates token status (active/dead/graduated)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE tokens SET status = ?, last_updated = ? WHERE address = ?',
              (status, int(time.time()), address))
    conn.commit()
    conn.close()


def mark_token_graduated(address):
    """Marks a Pump.fun token as graduated to Raydium."""
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE tokens SET graduated = 1, last_updated = ? WHERE address = ?',
              (int(time.time()), address))
    conn.commit()
    conn.close()


# =============================================================================
# SNAPSHOT OPERATIONS
# =============================================================================

def add_snapshot(token_address, price_usd, volume_5m, volume_1h, liquidity_usd,
                 market_cap_usd, holders, buys_5m, sells_5m):
    """Records a price/volume snapshot."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO snapshots 
        (token_address, timestamp, price_usd, volume_5m, volume_1h, liquidity_usd,
         market_cap_usd, holders, buys_5m, sells_5m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (token_address, int(time.time()), price_usd, volume_5m, volume_1h,
          liquidity_usd, market_cap_usd, holders, buys_5m, sells_5m))
    
    conn.commit()
    conn.close()


def get_recent_snapshots(token_address, minutes=30):
    """Gets snapshots from the last N minutes."""
    conn = get_connection()
    c = conn.cursor()
    cutoff = int(time.time()) - (minutes * 60)
    
    c.execute('''
        SELECT * FROM snapshots 
        WHERE token_address = ? AND timestamp > ?
        ORDER BY timestamp ASC
    ''', (token_address, cutoff))
    
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_latest_snapshot(token_address):
    """Gets the most recent snapshot for a token."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM snapshots 
        WHERE token_address = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (token_address,))
    
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# SCORE OPERATIONS
# =============================================================================

def add_score(token_address, discovery, structural, timing, context, 
              smart_wallet, final, timing_grade):
    """Records engine scores."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO scores 
        (token_address, timestamp, discovery_score, structural_score, timing_score,
         context_score, smart_wallet_score, final_score, timing_grade)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (token_address, int(time.time()), discovery, structural, timing,
          context, smart_wallet, final, timing_grade))
    
    conn.commit()
    conn.close()


def get_latest_score(token_address):
    """Gets the most recent score for a token."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM scores 
        WHERE token_address = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (token_address,))
    
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def add_wallet_snapshot(token_address, unique_buyers, entropy_normalized,
                         repeat_wallet_ratio, smart_wallet_hits, whale_hits):
    """
    Records a wallet behavior snapshot — the trend-tracking row. Called
    every scan cycle a token is processed, so behavior over time becomes
    queryable instead of only ever seeing the most recent moment.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        INSERT INTO wallet_snapshots
        (token_address, timestamp, unique_buyers, entropy_normalized,
         repeat_wallet_ratio, smart_wallet_hits, whale_hits)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (token_address, int(time.time()), unique_buyers, entropy_normalized,
          repeat_wallet_ratio, smart_wallet_hits, whale_hits))

    conn.commit()
    conn.close()


def get_wallet_snapshot_history(token_address):
    """Returns all wallet snapshots for a token, ordered by time — the trend."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        SELECT * FROM wallet_snapshots
        WHERE token_address = ?
        ORDER BY timestamp ASC
    ''', (token_address,))

    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_alert_scores_with_outcomes(hours=24):
    """
    For every token alerted in the given window, returns its component
    scores AT the moment of that first alert, joined with its outcome
    (peak MC reached since, and resulting multiplier). This is the real
    winners-vs-losers comparison using the bot's own scoring history.
    """
    conn = get_connection()
    c = conn.cursor()
    cutoff = int(time.time()) - (hours * 3600)

    c.execute('''
        SELECT a.token_address, a.market_cap_at_alert, a.timestamp as alert_time,
               t.symbol, t.name
        FROM alerts a
        JOIN tokens t ON a.token_address = t.address
        WHERE a.timestamp >= ?
        AND a.id = (
            SELECT MIN(id) FROM alerts a2 WHERE a2.token_address = a.token_address
        )
        ORDER BY a.timestamp ASC
    ''', (cutoff,))

    alerted = [dict(row) for row in c.fetchall()]
    results = []

    for entry in alerted:
        addr = entry["token_address"]
        alert_ts = entry["alert_time"]

        c.execute('''
            SELECT discovery_score, structural_score, timing_score,
                   context_score, smart_wallet_score, final_score, timing_grade
            FROM scores
            WHERE token_address = ? AND timestamp <= ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (addr, alert_ts))
        score_row = c.fetchone()
        score_data = dict(score_row) if score_row else {}

        c.execute('''
            SELECT MAX(market_cap_usd) as peak FROM snapshots
            WHERE token_address = ? AND timestamp >= ?
        ''', (addr, alert_ts))
        peak_row = c.fetchone()
        peak_mc = peak_row["peak"] if peak_row and peak_row["peak"] else 0
        alert_mc = entry.get("market_cap_at_alert", 0) or 0
        peak_mc = max(peak_mc, alert_mc)
        multiplier = (peak_mc / alert_mc) if alert_mc > 0 else 0

        results.append({
            "symbol": entry.get("symbol"),
            "alert_mc": alert_mc,
            "peak_mc": peak_mc,
            "multiplier": round(multiplier, 2),
            "discovery_score": score_data.get("discovery_score"),
            "structural_score": score_data.get("structural_score"),
            "timing_score": score_data.get("timing_score"),
            "context_score": score_data.get("context_score"),
            "smart_wallet_score": score_data.get("smart_wallet_score"),
            "final_score": score_data.get("final_score"),
        })

    conn.close()
    return results


# =============================================================================
# ALERT OPERATIONS
# =============================================================================

def add_alert(token_address, tier, final_score, price_at_alert, market_cap_at_alert, message_id=None):
    """Records a sent alert."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO alerts 
        (token_address, timestamp, tier, final_score, price_at_alert, 
         market_cap_at_alert, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (token_address, int(time.time()), tier, final_score, price_at_alert,
          market_cap_at_alert, message_id))
    
    alert_id = c.lastrowid
    conn.commit()
    conn.close()
    return alert_id


def get_last_alert(token_address):
    """Gets the most recent alert for a token."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM alerts 
        WHERE token_address = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (token_address,))
    
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_peak_market_cap(token_address, since_timestamp=None):
    """
    Returns the highest market_cap_usd ever recorded in snapshots
    for this token, optionally only counting snapshots after a given time.
    """
    conn = get_connection()
    c = conn.cursor()

    if since_timestamp:
        c.execute('''
            SELECT MAX(market_cap_usd) as peak FROM snapshots
            WHERE token_address = ? AND timestamp >= ?
        ''', (token_address, since_timestamp))
    else:
        c.execute('''
            SELECT MAX(market_cap_usd) as peak FROM snapshots
            WHERE token_address = ?
        ''', (token_address,))

    row = c.fetchone()
    conn.close()
    return row["peak"] if row and row["peak"] else 0


def get_alerts_in_window(hours=24):
    """
    Returns one row per token that received its FIRST alert within the
    given window (so a token alerted yesterday but still climbing today
    doesn't get re-listed as a 'new' entry in tonight's digest).
    """
    conn = get_connection()
    c = conn.cursor()
    cutoff = int(time.time()) - (hours * 3600)

    c.execute('''
        SELECT a.token_address, a.market_cap_at_alert, a.timestamp,
               t.symbol, t.name
        FROM alerts a
        JOIN tokens t ON a.token_address = t.address
        WHERE a.timestamp >= ?
        AND a.id = (
            SELECT MIN(id) FROM alerts a2 WHERE a2.token_address = a.token_address
        )
        ORDER BY a.timestamp ASC
    ''', (cutoff,))

    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def can_alert(token_address, cooldown_minutes):
    """Checks if enough time has passed since last alert."""
    last = get_last_alert(token_address)
    if not last:
        return True
    
    elapsed = int(time.time()) - last['timestamp']
    return elapsed >= (cooldown_minutes * 60)


# =============================================================================
# OUTCOME OPERATIONS
# =============================================================================

def add_outcome(alert_id, token_address, price_at_alert):
    """Creates an outcome record to track post-alert performance."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO outcomes (alert_id, token_address, price_at_alert)
        VALUES (?, ?, ?)
    ''', (alert_id, token_address, price_at_alert))
    
    conn.commit()
    conn.close()


def update_outcome(alert_id, **kwargs):
    """Updates outcome with price data at different intervals."""
    conn = get_connection()
    c = conn.cursor()
    
    # Build dynamic update query
    fields = []
    values = []
    for key, value in kwargs.items():
        fields.append(f"{key} = ?")
        values.append(value)
    values.append(alert_id)
    
    query = f"UPDATE outcomes SET {', '.join(fields)} WHERE alert_id = ?"
    c.execute(query, values)
    
    conn.commit()
    conn.close()


def get_pending_outcomes():
    """Gets outcomes that still need price updates."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        SELECT o.*, a.timestamp as alert_timestamp 
        FROM outcomes o
        JOIN alerts a ON o.alert_id = a.id
        WHERE o.price_1h IS NULL
    ''')
    
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# =============================================================================
# SMART WALLET OPERATIONS
# =============================================================================

def upsert_smart_wallet(address, total_trades, winning_trades, win_rate, avg_profit):
    """Inserts or updates a smart wallet."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO smart_wallets (address, total_trades, winning_trades, win_rate, avg_profit, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(address) DO UPDATE SET
            total_trades = ?, winning_trades = ?, win_rate = ?, avg_profit = ?, last_updated = ?
    ''', (address, total_trades, winning_trades, win_rate, avg_profit, int(time.time()),
          total_trades, winning_trades, win_rate, avg_profit, int(time.time())))
    
    conn.commit()
    conn.close()


def get_smart_wallets(min_win_rate=0.55):
    """Gets all qualified smart wallets."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('SELECT * FROM smart_wallets WHERE win_rate >= ?', (min_win_rate,))
    
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def is_smart_wallet(address):
    """Checks if an address is a known smart wallet."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('SELECT 1 FROM smart_wallets WHERE address = ? AND win_rate >= 0.55', (address,))
    result = c.fetchone()
    conn.close()
    return result is not None


# =============================================================================
# SECURITY CACHE OPERATIONS
# =============================================================================

def cache_security_scan(token_address, is_honeypot, has_freeze, has_mint, top_holder_pct):
    """Caches security scan results."""
    conn = get_connection()
    c = conn.cursor()

    # Defensive: None means "unknown", treat as False rather than crashing.
    is_honeypot = is_honeypot or False
    has_freeze = has_freeze or False
    has_mint = has_mint or False

    c.execute('''
        INSERT OR REPLACE INTO security_cache 
        (token_address, is_honeypot, has_freeze, has_mint, top_holder_pct, scanned_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (token_address, int(is_honeypot), int(has_freeze), int(has_mint), 
          top_holder_pct, int(time.time())))
    
    conn.commit()
    conn.close()


def get_security_cache(token_address, max_age_minutes=60):
    """Gets cached security scan if fresh enough."""
    conn = get_connection()
    c = conn.cursor()
    cutoff = int(time.time()) - (max_age_minutes * 60)
    
    c.execute('''
        SELECT * FROM security_cache 
        WHERE token_address = ? AND scanned_at > ?
    ''', (token_address, cutoff))
    
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# MARKET CONTEXT OPERATIONS
# =============================================================================

def add_market_context(sol_price, sol_change_24h, market_regime):
    """Records market context."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO market_context (timestamp, sol_price, sol_change_24h, market_regime)
        VALUES (?, ?, ?, ?)
    ''', (int(time.time()), sol_price, sol_change_24h, market_regime))
    
    conn.commit()
    conn.close()


def get_latest_market_context():
    """Gets the most recent market context."""
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('SELECT * FROM market_context ORDER BY timestamp DESC LIMIT 1')
    
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# CLEANUP OPERATIONS
# =============================================================================

def cleanup_old_data(days=7):
    """Removes data older than N days."""
    conn = get_connection()
    c = conn.cursor()
    cutoff = int(time.time()) - (days * 24 * 60 * 60)
    
    c.execute('DELETE FROM snapshots WHERE timestamp < ?', (cutoff,))
    c.execute('DELETE FROM scores WHERE timestamp < ?', (cutoff,))
    c.execute('DELETE FROM market_context WHERE timestamp < ?', (cutoff,))
    
    deleted = c.rowcount
    conn.commit()
    conn.close()
    
    if DEBUG_MODE:
        print(f"🧹 Cleaned up old data (cutoff: {days} days)")
    
    return deleted


def get_stats():
    """Gets database statistics."""
    conn = get_connection()
    c = conn.cursor()
    
    stats = {}
    c.execute('SELECT COUNT(*) FROM tokens WHERE status = "active"')
    stats['active_tokens'] = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM snapshots')
    stats['total_snapshots'] = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM alerts')
    stats['total_alerts'] = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM smart_wallets')
    stats['smart_wallets'] = c.fetchone()[0]
    
    conn.close()
    return stats


# =============================================================================
# INITIALIZATION
# =============================================================================

if __name__ == "__main__":
    init_database()
    print("\n📊 Database Stats:")
    stats = get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")