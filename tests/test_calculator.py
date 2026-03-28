"""
test_calculator.py
------------------
Unit tests for the pure rating math in calculator.py.
No network calls needed — all inputs are synthetic.

Run with: pytest tests/test_calculator.py -v
"""

import pytest
from ratings_calculator.calculator import (
    compute_pdga_rating,
    compute_lookback_window,
    build_used_rounds,
    project_rating,
    rounds_needed_for_target,
    ONE_YEAR_SECS,
    TWO_YEARS_SECS,
)

NOW = 1_700_000_000  # fixed timestamp for deterministic tests


def make_round(
    rating: int,
    days_ago: int,
    evaluated: str = "Yes",
    included:  str = "Yes",
    name:      str = "Test Event",
) -> dict:
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
        proj, _ = compute_pdga_rating([900] * 10)
        assert proj == 900

    def test_doubling_boosts_high_rounds(self):
        """Top quartile is doubled, so a high cluster should push rating above the simple mean."""
        ratings  = [900] * 8 + [950] * 4
        proj, _  = compute_pdga_rating(ratings)
        baseline = round(sum(ratings) / len(ratings))
        assert proj > baseline

    def test_outlier_dropped(self):
        """A very low round should be excluded and not drag down the result."""
        ratings    = [900] * 10 + [500]
        proj, cutoff = compute_pdga_rating(ratings)
        assert cutoff > 500
        assert proj > 800

    def test_fewer_than_8_no_doubling(self):
        """With fewer than 8 rounds, no doubling — just average the filtered set."""
        ratings  = [900, 910, 890, 905, 895]
        proj, _  = compute_pdga_rating(ratings)
        expected = round(sum(ratings) / len(ratings))
        assert proj == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_pdga_rating([])

    def test_cutoff_100_below_avg_when_tight(self):
        """When std dev is very small, cutoff should be avg - 100."""
        _, cutoff = compute_pdga_rating([900] * 20)
        assert cutoff == 800.0

    def test_cutoff_std_dev_based_when_spread(self):
        """When spread is large, the std-dev formula produces a cutoff below avg - 100."""
        ratings = list(range(800, 1000, 10))  # 20 rounds, wide spread
        avg = sum(ratings) / len(ratings)
        _, cutoff = compute_pdga_rating(ratings)
        assert cutoff < avg - 100


# ---------------------------------------------------------------------------
# compute_lookback_window
# ---------------------------------------------------------------------------

class TestLookbackWindow:
    def test_1_year_window_with_enough_rounds(self):
        rounds = [make_round(900, d) for d in range(0, 300, 30)]  # 10 rounds in past year
        most_recent, last_date = compute_lookback_window(rounds)
        assert most_recent == max(r["timestamp"] for r in rounds)
        assert last_date == most_recent - ONE_YEAR_SECS

    def test_extends_to_2_years_when_sparse(self):
        """Fewer than 8 rounds in 1 year → extend to 24 months."""
        rounds = [make_round(900, d) for d in [10, 20, 30, 40, 50, 60, 70]]  # 7 rounds
        _, last_date = compute_lookback_window(rounds)
        assert last_date == max(r["timestamp"] for r in rounds) - TWO_YEARS_SECS

    def test_anchors_to_most_recent_round_not_wall_clock(self):
        """last_date is anchored to the most recent ROUND, not today."""
        rounds = [make_round(900, d) for d in range(200, 500, 30)]
        most_recent, last_date = compute_lookback_window(rounds)
        assert most_recent == NOW - 200 * 86400
        assert last_date   == most_recent - ONE_YEAR_SECS

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_lookback_window([])


# ---------------------------------------------------------------------------
# build_used_rounds
# ---------------------------------------------------------------------------

class TestBuildUsedRounds:
    def test_excludes_pdga_dropped_outliers(self):
        """Rounds marked included=No must not appear in used_rounds."""
        rated = [
            make_round(900, 30,  evaluated="Yes", included="Yes"),
            make_round(500, 60,  evaluated="Yes", included="No"),
        ]
        used, _ = build_used_rounds(rated, [])
        assert all(r["rating"] != 500 for r in used)

    def test_excludes_rounds_outside_window(self):
        """Rounds older than the lookback cutoff must be excluded."""
        old  = make_round(900, 400, evaluated="Yes", included="Yes")
        new  = make_round(920, 10,  evaluated="Yes", included="Yes")
        used, last_date = build_used_rounds([old, new], [])
        assert all(r["timestamp"] > last_date for r in used)

    def test_whatif_rounds_present_in_used(self):
        """Hypothetical rounds must appear in used_rounds."""
        rated = [make_round(900, d, evaluated="Yes", included="Yes") for d in range(10, 200, 20)]
        used, _ = build_used_rounds(rated, [], whatif_ratings=[950, 960])
        hyp = [r for r in used if "Hypothetical" in r.get("name", "")]
        assert len(hyp) == 2


# ---------------------------------------------------------------------------
# project_rating
# ---------------------------------------------------------------------------

class TestProjectRating:
    def _rated(self, ratings: list[int]) -> list[dict]:
        return [
            make_round(r, (i + 1) * 20, evaluated="Yes", included="Yes")
            for i, r in enumerate(ratings)
        ]

    def test_stable_player(self):
        result = project_rating(self._rated([900] * 12), [])
        assert result["projected_rating"] == 900

    def test_whatif_high_rounds_increase_projection(self):
        rated = self._rated([900] * 10)
        base  = project_rating(rated, [])
        with_whatif = project_rating(rated, [], whatif_ratings=[960, 970])
        assert with_whatif["projected_rating"] >= base["projected_rating"]

    def test_result_has_required_keys(self):
        result = project_rating(self._rated([900] * 8), [])
        for key in ["projected_rating", "drop_below", "outgoing_rounds",
                    "incoming_rounds", "outlier_rounds"]:
            assert key in result


# ---------------------------------------------------------------------------
# rounds_needed_for_target
# ---------------------------------------------------------------------------

class TestRoundsNeededForTarget:
    def _base(self) -> list[dict]:
        return [
            make_round(900, (i + 1) * 20, evaluated="Yes", included="Yes")
            for i in range(10)
        ]

    def test_achievable_target(self):
        result = rounds_needed_for_target(self._base(), [], target_rating=910, num_rounds=3)
        assert result["achievable"] is True
        assert result["needed_avg"] is not None
        assert result["with_avg"] >= 910

    def test_unreachable_target(self):
        result = rounds_needed_for_target(self._base(), [], target_rating=1200, num_rounds=1)
        assert result["achievable"] is False

    def test_solver_answer_actually_reaches_target(self):
        """The needed_avg the solver returns must actually produce the claimed rating."""
        result = rounds_needed_for_target(self._base(), [], target_rating=915, num_rounds=4)
        if result["achievable"]:
            verify = project_rating(self._base(), [], whatif_ratings=result["example_rounds"])
            assert verify["projected_rating"] >= 915
