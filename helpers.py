"""
helpers.py - Utility Functions
"""

import time
from datetime import datetime


def format_number(value, decimals=2):
    """Formats number with K/M/B suffix."""
    if value is None:
        return "N/A"
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.{decimals}f}B"
    elif value >= 1_000_000:
        return f"${value/1_000_000:.{decimals}f}M"
    elif value >= 1_000:
        return f"${value/1_000:.{decimals}f}K"
    else:
        return f"${value:.{decimals}f}"


def format_percent(value, decimals=1):
    if value is None:
        return "N/A"
    return f"{value * 100:.{decimals}f}%"


def format_price(value):
    if value is None:
        return "N/A"
    if value < 0.00001:
        return f"${value:.10f}"
    elif value < 0.01:
        return f"${value:.6f}"
    elif value < 1:
        return f"${value:.4f}"
    else:
        return f"${value:.2f}"


def format_age(timestamp):
    if timestamp is None:
        return "Unknown"
    now = int(time.time())
    diff = now - timestamp
    if diff < 60:
        return f"{diff}s"
    elif diff < 3600:
        return f"{diff // 60}m"
    elif diff < 86400:
        return f"{diff // 3600}h"
    else:
        return f"{diff // 86400}d"


def safe_divide(a, b, default=0):
    if b == 0 or b is None:
        return default
    return a / b


def calculate_change(current, previous):
    if previous == 0 or previous is None:
        return 0
    return (current - previous) / previous


def clamp(value, min_val, max_val):
    return max(min_val, min(max_val, value))


def minutes_ago(minutes):
    return int(time.time()) - (minutes * 60)


def truncate_address(address, chars=4):
    if not address or len(address) < chars * 2:
        return address
    return f"{address[:chars]}...{address[-chars:]}"


if __name__ == "__main__":
    print("Testing helpers.py...")
    print(f"format_number(1234567): {format_number(1234567)}")
    print(f"format_percent(0.156): {format_percent(0.156)}")
    print(f"format_price(0.00000123): {format_price(0.00000123)}")
    print("✅ helpers.py working!")