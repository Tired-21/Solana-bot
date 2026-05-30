"""
timing.py - Timing Engine
Grades entry timing: A (very early) to F (very late).
Weight: 20% of final score
"""

import time
from config import TIMING_GRADES, DEBUG_MODE
from helpers import clamp


def calculate_timing_score(token_address, token_data, current_data):
    """
    Calculates timing score (0-100) and assigns grade A-F.
    """
    signals = []

    # Get token age in minutes
    created_at = (
        token_data.get("created_at") or
        token_data.get("pair_created_at") or
        current_data.get("pair_created_at")
    )

    if DEBUG_MODE:
        print(f"DEBUG timing: created_at={created_at}")

    if created_at:
        # Handle milliseconds
        if created_at > 1e12:
            created_at = created_at / 1000
        age_minutes = (time.time() - created_at) / 60
    else:
        age_minutes = 999  # Unknown age = assume late

    if DEBUG_MODE:
        print(f"DEBUG timing: age_minutes={age_minutes:.1f}")

    # Determine grade based on age
    grade = "F"
    multiplier = 0.5
    label = "Very Late"

    for g in ["A", "B", "C", "D", "F"]:
        if age_minutes <= TIMING_GRADES[g]["max_age"]:
            grade = g
            multiplier = TIMING_GRADES[g]["multiplier"]
            label = TIMING_GRADES[g]["label"]
            break

    # Base score from grade
    grade_scores = {"A": 100, "B": 80, "C": 60, "D": 40, "F": 20}
    score = grade_scores.get(grade, 20)

    signals.append(f"⏱️ Age: {age_minutes:.0f}m ({label})")

    # Adjust based on holder count
    holders = current_data.get("holders", 0)
    if holders > 0:
        if holders < TIMING_GRADES.get("holders_early", 50):
            score += 10
            signals.append(f"Early holder count: {holders}")
        elif holders > TIMING_GRADES.get("holders_late", 500):
            score -= 10
            signals.append(f"High holder count: {holders}")

    # Adjust based on market cap
    mc = current_data.get("market_cap_usd", 0)
    if mc > 0:
        if mc < 50000:
            score += 10
            signals.append("Low MC entry")
        elif mc > 500000:
            score -= 10
            signals.append("High MC entry")

    final_score = clamp(score, 0, 100)

    if DEBUG_MODE:
        print(f"  ⏱️ Timing: {final_score} (Grade {grade})")

    return {
        "score": final_score,
        "grade": grade,
        "multiplier": multiplier,
        "age_minutes": age_minutes,
        "signals": signals
    }


def get_timing_grade(age_minutes):
    """Quick helper to get just the grade."""
    for g in ["A", "B", "C", "D", "F"]:
        if age_minutes <= TIMING_GRADES[g]["max_age"]:
            return g
    return "F"


if __name__ == "__main__":
    print("Testing timing.py...")

    # Mock early token (3 minutes old)
    mock_token = {"created_at": time.time() - 180}
    mock_current = {"holders": 30, "market_cap_usd": 25000}

    result = calculate_timing_score("test", mock_token, mock_current)

    print(f"\nTiming Score: {result['score']}/100")
    print(f"Grade: {result['grade']}")
    print(f"Age: {result['age_minutes']:.1f} minutes")
    print(f"Multiplier: {result['multiplier']}x")
    print("Signals:")
    for s in result['signals']:
        print(f"  {s}")

    # Test late token
    print("\n--- Testing late token (2 hours old) ---")
    mock_token_late = {"created_at": time.time() - 7200}
    result2 = calculate_timing_score("test", mock_token_late, mock_current)
    print(f"Grade: {result2['grade']} ({result2['age_minutes']:.0f} min)")

    print("\n✅ timing.py working!")