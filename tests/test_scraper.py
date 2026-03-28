"""
test_scraper.py
---------------
Smoke tests that hit the real PDGA website to verify the scraper handles
edge cases: league-only players, infrequent players, inactive players, etc.

Run with:
    pytest tests/test_scraper.py -v --timeout=60

These tests require internet access and are intentionally slow.
Mark them with -m smoke if you want to keep them separate from unit tests.
"""

import pytest
from pdga_rater.scraper import load_player_data, FetchError, ParseError
from pdga_rater.calculator import project_rating

# ---------------------------------------------------------------------------
# Test player profiles — chosen to cover specific edge cases
# ---------------------------------------------------------------------------
# Each entry: (pdga_number, description, expect_success)
# Add more numbers here as you discover new edge cases.
SMOKE_PLAYERS = [
    # Typical active player — baseline sanity check
    ("50160",  "active touring pro",             True),
    # Player who only plays leagues
    ("52630",  "league-only player",             True),
    # Very infrequent player (may trigger 24-month lookback)
    ("75000",  "infrequent recreational player", True),
    # Player with no recent activity — may have no projection
    ("1",      "PDGA member #1 (historical)",    True),
]


@pytest.mark.parametrize("pdga_number,description,expect_success", SMOKE_PLAYERS)
def test_load_and_project(pdga_number: str, description: str, expect_success: bool):
    """
    For each test player: load data, attempt projection, validate output shape.
    Does NOT assert exact rating values — just that we get a sane result.
    """
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

    # May have no evaluated rounds (very new member, inactive, etc.)
    if not data["tournaments"] and not data["new_tournaments"]:
        pytest.skip(f"[{pdga_number}] {description} — no rounds to project")

    try:
        result = project_rating(data["tournaments"], data["new_tournaments"])
    except ValueError as e:
        pytest.skip(f"[{pdga_number}] {description} — not enough rounds to project: {e}")
        return

    assert 400 <= result["projected_rating"] <= 1100, \
        f"[{pdga_number}] projected_rating {result['projected_rating']} out of plausible range"
    assert result["drop_below"] > 0
    assert isinstance(result["outgoing_rounds"],  list)
    assert isinstance(result["incoming_rounds"],  list)
    assert isinstance(result["outlier_rounds"],   list)


def test_invalid_pdga_number():
    """A clearly invalid PDGA number should raise FetchError or ParseError, not crash."""
    with pytest.raises((FetchError, ParseError)):
        load_player_data("00000000")


def test_cache_hit_returns_same_result():
    """
    Fetching the same player twice should return consistent results
    (second call hits cache).
    """
    pdga = "50160"
    data1 = load_player_data(pdga)
    data2 = load_player_data(pdga)  # should hit cache

    assert data1["current_rating"] == data2["current_rating"]
    assert len(data1["tournaments"]) == len(data2["tournaments"])
