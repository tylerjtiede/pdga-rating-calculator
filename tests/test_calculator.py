"""
test_calculator.py
------------------
Unit tests for the pure rating math in calculator.py.
No network calls needed — all inputs are synthetic.
"""

import pytest
from pdga_rater.calculator import (
    compute_pdga_rating,
    compute_lookback_window,
    build_used_rounds,
    project_rating,
    rounds_needed_for_target,
    ONE_YEAR_SECS,
    TWO_YEARS_SECS,
)

NOW = 1_700_000_000  # fixed "now" for deterministic tests


def make_round(rating: int, days_ago: int, evaluated="Yes", included="Yes", name="Test Event") -> dict:
    return {
        "name":      name,
        "rating":    rating,
        "timestamp": NOW - days_ago * 86400,
        "round":     1,
        "evaluated": evaluated,
        "included":  included,
    }


# ---------------------------------------------------------------------------
# compute_pdga_rating
# ---------------------------------------------------------------------------

class TestComputePdgaRating:
    def test_basic_average(self):
        """All identical ratings → projected equals that rating."""
        ratings = [900] * 10
        proj, cutoff = compute_pdga_rating(ratings)
        assert proj == 900

    def test_doubling_boosts_high_rounds(self):
        """Top quartile is doubled, so a high cluster should push rating up."""
        # 8 rounds at 900, 4 at 950 — doubling the top 3 (950s) should lift the avg
        ratings = [900] * 8 + [950] * 4
        proj, _ = compute_pdga_rating(ratings)
        baseline = round(sum(ratings) / len(ratings))
        assert proj > baseline

    def test_outlier_dropped(self):
        """A very low round should be excluded from the calculation."""
        ratings = [900] * 10 + [500]
        proj, cutoff = compute_pdga_rating(ratings)
        assert 500 < cutoff  # 500 is below the cutoff
        assert proj > 800    # result should be near 900, not dragged down

    def test_fewer_than_8_no_doubling(self):
        """With fewer than 8 rounds, no doubling — just average the filtered set."""
        ratings = [900, 910, 890, 905, 895]
        proj, _ = compute_pdga_rating(ratings)
        expected = round(sum(ratings) / len(ratings))
        assert proj == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_pdga_rating([])

    def test_cutoff_100_below_avg(self):
        """When std dev is small, cutoff should be avg - 100."""
        ratings = [900] * 20
        _, cutoff = compute_pdga_rating(ratings)
        assert cutoff == 800.0

    def test_cutoff_std_dev_based(self):
        """When spread is large, cutoff uses 2.5 * std dev."""
        # std dev of 60 → cutoff ~avg - 150, but bounded by avg - 100
        ratings = list(range(800, 1000, 10))  # 20 rounds, wide spread
        avg = sum(ratings) / len(ratings)
        _, cutoff = compute_pdga_rating(ratings)
        assert cutoff < avg - 100  # std-based cutoff wins here


# ---------------------------------------------------------------------------
# compute_lookback_window
# ---------------------------------------------------------------------------

class TestLookbackWindow:
    def test_1_year_window_with_enough_rounds(self):
        rounds = [make_round(900, d) for d in range(0, 300, 30)]  # 10 rounds in last year
        most_recent, last_date = compute_lookback_window(rounds)
        assert most_recent == max(r["timestamp"] for r in rounds)
        expected_cutoff = most_recent - ONE_YEAR_SECS
        assert last_date == expected_cutoff

    def test_extends_to_2_years_when_sparse(self):
        """Fewer than 8 rounds in 1 year → extend to 24 months."""
        rounds = [make_round(900, d) for d in [10, 20, 30, 40, 50, 60, 70]]  # 7 rounds
        most_recent, last_date = compute_lookback_window(rounds)
        assert last_date == most_recent - TWO_YEARS_SECS

    def test_anchors_to_most_recent_round_not_today(self):
        """last_date anchors to most recent ROUND timestamp, not wall clock."""
        # Most recent round was 200 days ago
        rounds = [make_round(900, d) for d in range(200, 500, 30)]
        most_recent, last_date = compute_lookback_window(rounds)
        assert most_recent == NOW - 200 * 86400
        assert last_date == most_recent - ONE_YEAR_SECS

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_lookback_window([])


# ---------------------------------------------------------------------------
# build_used_rounds
# ---------------------------------------------------------------------------

class TestBuildUsedRounds:
    def test_excludes_pdga_dropped_outliers(self):
        """Rounds marked included=No should not appear in used_rounds."""
        rated = [
            make_round(900, 30,  evaluated="Yes", included="Yes"),
            make_round(500, 60,  evaluated="Yes", included="No"),   # PDGA dropped
        ]
        new = []
        used, _ = build_used_rounds(rated, new)
        assert all(r["rating"] != 500 for r in used)

    def test_excludes_rounds_outside_window(self):
        """Rounds older than the lookback cutoff should be excluded."""
        old = make_round(900, 400, evaluated="Yes", included="Yes")   # outside 1yr
        new_r = make_round(920, 10, evaluated="Yes", included="Yes")  # inside
        used, last_date = build_used_rounds([old, new_r], [])
        assert all(r["timestamp"] > last_date for r in used)

    def test_whatif_rounds_injected(self):
        """Hypothetical rounds should appear in used_rounds."""
        rated = [make_round(900, d, evaluated="Yes", included="Yes") for d in range(10, 200, 20)]
        used, _ = build_used_rounds(rated, [], whatif_ratings=[950, 960])
        hyp = [r for r in used if "Hypothetical" in r.get("name", "")]
        assert len(hyp) == 2


# ---------------------------------------------------------------------------
# project_rating (integration)
# ---------------------------------------------------------------------------

class TestProjectRating:
    def _make_rated_set(self, ratings: list[int]) -> list[dict]:
        return [
            make_round(r, (i + 1) * 20, evaluated="Yes", included="Yes")
            for i, r in enumerate(ratings)
        ]

    def test_stable_player(self):
        """Player with consistent rounds should get a stable projection."""
        rated = self._make_rated_set([900] * 12)
        result = project_rating(rated, [])
        assert result["projected_rating"] == 900

    def test_whatif_increases_with_high_rounds(self):
        """Adding high hypothetical rounds should increase projected rating."""
        rated = self._make_rated_set([900] * 10)
        base = project_rating(rated, [])
        with_whatif = project_rating(rated, [], whatif_ratings=[960, 970])
        assert with_whatif["projected_rating"] >= base["projected_rating"]

    def test_result_keys_present(self):
        rated = self._make_rated_set([900] * 8)
        result = project_rating(rated, [])
        for key in ["projected_rating", "drop_below", "outgoing_rounds", "incoming_rounds", "outlier_rounds"]:
            assert key in result


# ---------------------------------------------------------------------------
# rounds_needed_for_target
# ---------------------------------------------------------------------------

class TestRoundsNeededForTarget:
    def _base_tournaments(self) -> list[dict]:
        return [
            make_round(900, (i + 1) * 20, evaluated="Yes", included="Yes")
            for i in range(10)
        ]

    def test_achievable_target(self):
        rated = self._base_tournaments()
        result = rounds_needed_for_target(rated, [], target_rating=910, num_rounds=3)
        assert result["achievable"] is True
        assert result["needed_avg"] is not None
        assert result["with_avg"] >= 910

    def test_unreachable_target(self):
        rated = self._base_tournaments()
        result = rounds_needed_for_target(rated, [], target_rating=1200, num_rounds=1)
        assert result["achievable"] is False

    def test_needed_avg_actually_reaches_target(self):
        """Verify the solver's answer actually produces the claimed rating."""
        rated = self._base_tournaments()
        target = 915
        result = rounds_needed_for_target(rated, [], target_rating=target, num_rounds=4)
        if result["achievable"]:
            verify = project_rating(rated, [], whatif_ratings=result["example_rounds"])
            assert verify["projected_rating"] >= target
