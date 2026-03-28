"""
test_history.py
---------------
Math validation tests: compare our calculator's output against real PDGA
rating history to verify our algorithm matches the official computation.

Strategy:
  For each historical rating update, we reconstruct the round set that was
  active at that point in time and run our calculator. The result should be
  within ±2 of the officially published rating.

Run with:
    pytest tests/test_history.py -v --timeout=120

Requires internet access. Uses real PDGA player data.
"""

import pytest
from datetime import datetime

from pdga_rater.scraper  import (
    fetch_player_pages,
    scrape_current_rating,
    scrape_detail_tournaments,
    scrape_rating_history,
)
from pdga_rater.calculator import (
    compute_lookback_window,
    compute_pdga_rating,
    ONE_YEAR_SECS,
    TWO_YEARS_SECS,
    MIN_ROUNDS_1_YEAR,
)

TOLERANCE = 2  # ±2 rating points

# ---------------------------------------------------------------------------
# Players to validate against their history.
# Pick players with varied profiles to stress different code paths.
# Add more as you discover discrepancies.
# ---------------------------------------------------------------------------
HISTORY_PLAYERS = [
    "50160",   # active touring pro, many rounds
    "150375",  # the bug reporter — good regression target
    "52630",   # league-heavy player
]


def reconstruct_rating_at(
    tournaments:    list[dict],
    as_of_ts:       int,
) -> int | None:
    """
    Reconstruct what our calculator would have produced for a player
    at a given point in time (as_of_ts), using only rounds that were
    rated and evaluated on or before that timestamp.

    Returns the projected rating, or None if there aren't enough rounds.
    """
    # Only include rounds that existed at as_of_ts
    rated_at_time = [
        t for t in tournaments
        if t.get("evaluated") == "Yes"
        and t.get("included") == "Yes"
        and t["timestamp"] <= as_of_ts
    ]

    if not rated_at_time:
        return None

    # Apply lookback window anchored at as_of_ts
    most_recent = max(t["timestamp"] for t in rated_at_time)
    last_date   = most_recent - ONE_YEAR_SECS
    in_window   = [t for t in rated_at_time if t["timestamp"] > last_date]

    if len(in_window) < MIN_ROUNDS_1_YEAR:
        last_date = most_recent - TWO_YEARS_SECS
        in_window = [t for t in rated_at_time if t["timestamp"] > last_date]

    if not in_window:
        return None

    ratings = [t["rating"] for t in in_window]
    try:
        projected, _ = compute_pdga_rating(ratings)
        return projected
    except ValueError:
        return None


@pytest.mark.parametrize("pdga_number", HISTORY_PLAYERS)
def test_history_math(pdga_number: str):
    """
    For each official rating update in the player's history, verify that
    our algorithm produces a result within ±2 of the published rating.
    """
    pages = fetch_player_pages(pdga_number)
    tournaments  = scrape_detail_tournaments(pages["detail"])
    history      = scrape_rating_history(pages["history"])

    if not history:
        pytest.skip(f"[{pdga_number}] No rating history found.")

    if not tournaments:
        pytest.skip(f"[{pdga_number}] No rated tournament rounds found.")

    failures   = []
    tested     = 0
    skipped    = 0

    for update in history:
        official_rating = update["rating"]
        update_ts       = update["timestamp"]

        projected = reconstruct_rating_at(tournaments, as_of_ts=update_ts)

        if projected is None:
            skipped += 1
            continue

        tested += 1
        diff = abs(projected - official_rating)

        if diff > TOLERANCE:
            failures.append(
                f"  {update['date_str']}: projected={projected}, "
                f"official={official_rating}, diff={diff}"
            )

    if tested == 0:
        pytest.skip(f"[{pdga_number}] Could not reconstruct any historical ratings.")

    summary = (
        f"[{pdga_number}] Tested {tested} updates, skipped {skipped}. "
        f"Failures: {len(failures)}/{tested}"
    )

    if failures:
        failure_detail = "\n".join(failures[:10])  # cap output for readability
        pytest.fail(f"{summary}\n{failure_detail}")
    else:
        print(f"\n✓ {summary}")  # visible with pytest -s


@pytest.mark.parametrize("pdga_number", HISTORY_PLAYERS)
def test_history_pass_rate(pdga_number: str):
    """
    Softer version: assert that at least 80% of historical updates match
    within tolerance. Accounts for edge cases we may not handle perfectly.
    """
    pages = fetch_player_pages(pdga_number)
    tournaments = scrape_detail_tournaments(pages["detail"])
    history     = scrape_rating_history(pages["history"])

    if not history or not tournaments:
        pytest.skip(f"[{pdga_number}] Insufficient data.")

    passed  = 0
    tested  = 0

    for update in history:
        projected = reconstruct_rating_at(tournaments, as_of_ts=update["timestamp"])
        if projected is None:
            continue
        tested += 1
        if abs(projected - update["rating"]) <= TOLERANCE:
            passed += 1

    if tested == 0:
        pytest.skip(f"[{pdga_number}] No testable updates.")

    pass_rate = passed / tested
    assert pass_rate >= 0.80, (
        f"[{pdga_number}] Pass rate {pass_rate:.0%} below 80% "
        f"({passed}/{tested} updates within ±{TOLERANCE})"
    )
