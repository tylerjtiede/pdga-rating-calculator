"""
calculator.py
-------------
Pure rating math. No I/O, no side effects — all functions are unit-testable
without any network mocking.
"""

import math
from datetime import datetime
from operator import itemgetter

import numpy as np

ONE_YEAR_SECS     = 365 * 24 * 60 * 60
TWO_YEARS_SECS    = 2 * ONE_YEAR_SECS
MIN_ROUNDS_1_YEAR = 8


# ---------------------------------------------------------------------------
# Lookback window
# ---------------------------------------------------------------------------

def compute_lookback_window(rounds: list[dict]) -> tuple[int, int]:
    """
    Determine the lookback cutoff timestamp per PDGA rules:
      - 12 months back from the most recent rated round.
      - If fewer than 8 rounds exist in that window, extend to 24 months.

    Returns (most_recent_timestamp, last_date).
    """
    if not rounds:
        raise ValueError("No rounds provided to compute lookback window.")

    most_recent = max(r["timestamp"] for r in rounds)
    last_date   = most_recent - ONE_YEAR_SECS

    in_window = [r for r in rounds if r["timestamp"] > last_date]
    if len(in_window) < MIN_ROUNDS_1_YEAR:
        last_date = most_recent - TWO_YEARS_SECS

    return most_recent, last_date


# ---------------------------------------------------------------------------
# Core rating computation
# ---------------------------------------------------------------------------

def compute_pdga_rating(ratings: list[int]) -> tuple[int, float]:
    """
    Compute projected PDGA rating and outlier cutoff from a flat list of round ratings.
    Returns (projected_rating, drop_below_cutoff).
    """
    if not ratings:
        raise ValueError("No ratings provided.")

    arr       = np.array(ratings, dtype=float)
    avg       = float(np.mean(arr))
    drop_below = float(np.round(max(avg - 100.0, avg - 2.5 * float(np.std(arr)))))

    filtered = [r for r in ratings if r >= drop_below]
    if not filtered:
        raise ValueError("All rounds were filtered as outliers — cannot compute rating.")

    doubled = filtered[: len(filtered) // 4]

    if len(filtered) < MIN_ROUNDS_1_YEAR:
        projected = round(float(np.mean(filtered)))
    else:
        projected = round(float(np.mean(filtered + doubled)))

    return projected, drop_below


# ---------------------------------------------------------------------------
# Build the round set used for computation
# ---------------------------------------------------------------------------

def build_used_rounds(
    tournaments:     list[dict],
    new_tournaments: list[dict],
    whatif_ratings:  list[int] | None = None,
) -> tuple[list[dict], int]:
    """
    Assemble the full set of rounds that feed into the rating calculation,
    applying PDGA lookback rules and respecting already-dropped outliers.

    Returns (used_rounds, last_date).
    """
    now = int(datetime.now().timestamp())

    whatif_rounds: list[dict] = []
    if whatif_ratings:
        for i, r in enumerate(whatif_ratings):
            whatif_rounds.append({
                "name":      f"Hypothetical Round {i + 1}",
                "rating":    r,
                "timestamp": now,
                "round":     i + 1,
            })

    all_new = new_tournaments + whatif_rounds

    all_candidates = all_new + [t for t in tournaments if t.get("evaluated") == "Yes"]
    if not all_candidates:
        raise ValueError("No evaluated rounds found for this player.")

    _, last_date = compute_lookback_window(all_candidates)

    used_rounds = all_new + [
        t for t in tournaments
        if t.get("evaluated") == "Yes"
        and t["timestamp"] > last_date
        and t.get("included") == "Yes"   # respect rounds PDGA already dropped as outliers
    ]

    return used_rounds, last_date


def project_rating(
    tournaments:     list[dict],
    new_tournaments: list[dict],
    whatif_ratings:  list[int] | None = None,
) -> dict:
    """
    Full projection pipeline. Returns a result dict with all display data.
    """
    used_rounds, last_date = build_used_rounds(tournaments, new_tournaments, whatif_ratings)

    sorted_rounds = sorted(used_rounds, key=itemgetter("timestamp"), reverse=True)
    ratings_list  = [r["rating"] for r in sorted_rounds]

    projected, drop_below = compute_pdga_rating(ratings_list)

    now = int(datetime.now().timestamp())
    whatif_rounds = [
        r for r in used_rounds
        if r.get("name", "").startswith("Hypothetical Round")
        and r["timestamp"] >= now - 5
    ]

    outgoing = [
        t for t in tournaments
        if t.get("evaluated") == "Yes" and t["timestamp"] <= last_date
    ]
    incoming = sorted(
        [r for r in used_rounds if r not in [
            t for t in tournaments
            if t.get("evaluated") == "Yes" and t["timestamp"] > last_date
        ]],
        key=lambda x: (x.get("timestamp", 0), x.get("round", 0)),
    )
    outliers = [r for r in used_rounds if r["rating"] < drop_below]

    return {
        "projected_rating": projected,
        "drop_below":       drop_below,
        "outgoing_rounds":  outgoing,
        "incoming_rounds":  incoming,
        "outlier_rounds":   outliers,
        "used_rounds":      used_rounds,
        "last_date":        last_date,
    }


# ---------------------------------------------------------------------------
# What-if: target rating solver
# ---------------------------------------------------------------------------

def rounds_needed_for_target(
    tournaments:     list[dict],
    new_tournaments: list[dict],
    target_rating:   int,
    num_rounds:      int,
) -> dict:
    """
    Binary-search for the average round rating needed across `num_rounds`
    hypothetical rounds to reach `target_rating`.

    Returns a dict with:
        needed_avg     - average rating per round needed
        achievable     - whether the target is mathematically reachable
        with_avg       - what the projected rating would be at needed_avg
        example_rounds - list of `num_rounds` ints all equal to needed_avg
    """
    def trial(avg_rating: int) -> int:
        hypotheticals = [avg_rating] * num_rounds
        result = project_rating(tournaments, new_tournaments, hypotheticals)
        return result["projected_rating"]

    # Quick bounds check
    low, high = 300, 1100
    if trial(high) < target_rating:
        return {
            "achievable":     False,
            "needed_avg":     None,
            "with_avg":       trial(high),
            "example_rounds": [high] * num_rounds,
            "message":        f"Target {target_rating} is not achievable in {num_rounds} round(s) — "
                              f"even averaging {high} only gets you to {trial(high)}.",
        }
    if trial(low) >= target_rating:
        return {
            "achievable":     True,
            "needed_avg":     low,
            "with_avg":       trial(low),
            "example_rounds": [low] * num_rounds,
            "message":        f"You'd reach {target_rating} even averaging just {low}.",
        }

    # Binary search for the minimum average
    while low < high - 1:
        mid = (low + high) // 2
        if trial(mid) >= target_rating:
            high = mid
        else:
            low = mid

    needed = high
    actual = trial(needed)
    return {
        "achievable":     True,
        "needed_avg":     needed,
        "with_avg":       actual,
        "example_rounds": [needed] * num_rounds,
        "message":        f"Average {needed} across {num_rounds} round(s) → projected {actual}.",
    }
