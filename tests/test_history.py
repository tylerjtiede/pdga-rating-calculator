"""
test_history.py
---------------
Math validation: compare our calculator against real PDGA rating history.

For each official rating update in a player's history, we reconstruct the
round set that was active at that point in time, run our calculator, and
assert the result is within ±2 of the officially published rating.

Run with:
    pytest tests/test_history.py -v --timeout=120

Requires internet access. Slow (~2min). Run on schedule, not every push.

─────────────────────────────────────────────────────────────────────────────
MAINTENANCE NOTE — update HISTORY_PLAYERS as needed.
Good candidates are players whose rating history you can manually verify.
The bug reporter (#150375) is a strong regression target since we already
know the expected output for specific updates. Your own PDGA number is also
a great addition — you can verify the math yourself.
─────────────────────────────────────────────────────────────────────────────
"""

import pytest

from ratings_calculator.scraper import (
    fetch_player_pages,
    scrape_detail_tournaments,
    scrape_rating_history,
)
from ratings_calculator.calculator import (
    compute_pdga_rating,
    ONE_YEAR_SECS,
    TWO_YEARS_SECS,
    MIN_ROUNDS_1_YEAR,
)

TOLERANCE = 2  # ±2 rating points

# ---------------------------------------------------------------------------
# Players to validate.
# TODO: Add your own PDGA number and any other players you can manually verify.
# ---------------------------------------------------------------------------
HISTORY_PLAYERS = [
    "178379",   # developer (me)
    "150375",   # the bug reporter — specific updates already manually verified
    "177699",   # league-heavy player
    "75412",    # touring pro
]


# ---------------------------------------------------------------------------
# Reconstruction logic
# ---------------------------------------------------------------------------

def reconstruct_rating_at(tournaments: list[dict], as_of_ts: int) -> int | None:
    """
    Reconstruct our calculator's output for a player at a historical point in time,
    using only rounds that were rated and included on or before as_of_ts.

    Returns the projected rating, or None if there are not enough rounds.
    """
    rated_at_time = [
        t for t in tournaments
        if t.get("evaluated") == "Yes"
        and t.get("included")  == "Yes"
        and t["timestamp"]     <= as_of_ts
    ]
    if not rated_at_time:
        return None

    most_recent = max(t["timestamp"] for t in rated_at_time)
    last_date   = most_recent - ONE_YEAR_SECS
    in_window   = [t for t in rated_at_time if t["timestamp"] > last_date]

    if len(in_window) < MIN_ROUNDS_1_YEAR:
        last_date = most_recent - TWO_YEARS_SECS
        in_window = [t for t in rated_at_time if t["timestamp"] > last_date]

    if not in_window:
        return None

    try:
        projected, _ = compute_pdga_rating([t["rating"] for t in in_window])
        return projected
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pdga_number", HISTORY_PLAYERS)
def test_history_math_within_tolerance(pdga_number: str):
    """
    For each official rating update, our projection must be within ±2.
    Lists all failures so you can see the full picture, not just the first miss.
    """
    pages       = fetch_player_pages(pdga_number)
    tournaments = scrape_detail_tournaments(pages["detail"])
    history     = scrape_rating_history(pages["history"])

    if not history:
        pytest.skip(f"[{pdga_number}] No rating history found.")
    if not tournaments:
        pytest.skip(f"[{pdga_number}] No rated tournament rounds found.")

    failures = []
    tested   = 0
    skipped  = 0

    for update in history:
        projected = reconstruct_rating_at(tournaments, as_of_ts=update["timestamp"])
        if projected is None:
            skipped += 1
            continue

        tested += 1
        diff = abs(projected - update["rating"])
        if diff > TOLERANCE:
            failures.append(
                f"  {update['date_str']}: projected={projected}, "
                f"official={update['rating']}, diff={diff:+}"
            )

    if tested == 0:
        pytest.skip(f"[{pdga_number}] Could not reconstruct any historical ratings.")

    summary = (
        f"[{pdga_number}] {tested} updates tested, {skipped} skipped, "
        f"{len(failures)} failed."
    )
    if failures:
        pytest.fail(f"{summary}\n" + "\n".join(failures[:10]))
    else:
        print(f"\n✓ {summary}")


@pytest.mark.parametrize("pdga_number", HISTORY_PLAYERS)
def test_history_pass_rate_80_percent(pdga_number: str):
    """
    Softer check: at least 80% of historical updates must match within ±2.
    Exists to account for edge cases we may not handle perfectly yet.
    If this passes but test_history_math_within_tolerance fails, it means
    there are occasional misses worth investigating but not a systemic bug.
    """
    pages       = fetch_player_pages(pdga_number)
    tournaments = scrape_detail_tournaments(pages["detail"])
    history     = scrape_rating_history(pages["history"])

    if not history or not tournaments:
        pytest.skip(f"[{pdga_number}] Insufficient data.")

    passed = 0
    tested = 0

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
        f"[{pdga_number}] Pass rate {pass_rate:.0%} ({passed}/{tested}) "
        f"is below the 80% threshold."
    )
