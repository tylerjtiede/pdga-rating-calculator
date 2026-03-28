"""
test_scraper.py
---------------
Smoke tests against the real PDGA website. Verifies the scraper handles
a range of player profiles without crashing or returning nonsense.

Run with:
    pytest tests/test_scraper.py -v --timeout=60

Requires internet access. Slow (~30s). Run on schedule, not every push.

─────────────────────────────────────────────────────────────────────────────
MAINTENANCE NOTE — update these player numbers as needed.
Each entry should be a real PDGA number that fits the described profile.
Verify a player fits their category before adding them here.
─────────────────────────────────────────────────────────────────────────────
"""

import pytest
from ratings_calculator.scraper    import load_player_data, FetchError, ParseError
from ratings_calculator.calculator import project_rating

# ---------------------------------------------------------------------------
# Test player roster
# fmt: (pdga_number, description, expect_success)
#
# TODO: Replace placeholder numbers with real players you've verified.
#   - "active player"      → someone you know plays regularly (e.g. your own #)
#   - "league-only"        → a player whose only rounds are league events
#   - "infrequent"         → someone with <8 rounds in the past year
#   - "historical/inactive"→ a very old or inactive member
# ---------------------------------------------------------------------------
SMOKE_PLAYERS = [
    # ── Replace these with verified PDGA numbers ──────────────────────────
    ("178379",    "active player",       True),
    ("150375",    "the bug reporter — regression target",   True),
    ("177699",    "league-only player",  True),
    ("73800",     "infrequent player",   True),
    # ── These edge cases are stable regardless of who the player is ────────
    ("1",              "PDGA member #1 — very old, likely inactive",       True),
]


@pytest.mark.parametrize("pdga_number,description,expect_success", SMOKE_PLAYERS)
def test_load_and_project(pdga_number: str, description: str, expect_success: bool):
    """
    Load data for each player and attempt a projection.
    Checks output shape and plausibility, not exact values.
    """
    if pdga_number.startswith("TODO"):
        pytest.skip(f"Placeholder not yet replaced: {description}")

    try:
        data = load_player_data(pdga_number)
    except (FetchError, ParseError) as e:
        if expect_success:
            pytest.fail(f"[{pdga_number}] {description} — unexpected error: {e}")
        return

    assert isinstance(data["current_rating"], int), \
        f"[{pdga_number}] current_rating should be an int"
    assert data["current_rating"] > 0, \
        f"[{pdga_number}] current_rating should be positive"

    if not data["tournaments"] and not data["new_tournaments"]:
        pytest.skip(f"[{pdga_number}] {description} — no rounds to project")

    try:
        result = project_rating(data["tournaments"], data["new_tournaments"])
    except ValueError:
        pytest.skip(f"[{pdga_number}] {description} — not enough rounds to project")
        return

    assert 400 <= result["projected_rating"] <= 1100, \
        f"[{pdga_number}] projected {result['projected_rating']} is outside plausible range"
    assert result["drop_below"] > 0
    assert isinstance(result["outgoing_rounds"], list)
    assert isinstance(result["incoming_rounds"], list)
    assert isinstance(result["outlier_rounds"],  list)


def test_invalid_pdga_number():
    """A clearly invalid PDGA number should raise FetchError or ParseError, not crash."""
    with pytest.raises((FetchError, ParseError)):
        load_player_data("00000000")


def test_cache_returns_consistent_result():
    """Fetching the same player twice should return identical data (second call hits cache)."""
    pdga = "150375"
    data1 = load_player_data(pdga)
    data2 = load_player_data(pdga)

    assert data1["current_rating"]     == data2["current_rating"]
    assert len(data1["tournaments"])   == len(data2["tournaments"])
