# pdga-ratings-calculator

Project your PDGA rating before the official monthly update.

## Installation

```bash
git clone https://github.com/you/ratings_calculator
cd ratings_calculator
pip install -e ".[dev]"
```

## Usage

**CLI**
```bash
# Basic projection
pdga-ratings --pdga 12345

# What-if: see how hypothetical rounds affect your rating
pdga-ratings --pdga 12345 --whatif 950,960,970

# Target solver: what do I need to average to hit 950 over 3 rounds?
pdga-ratings --pdga 12345 --target 950 --rounds 3

# Force re-fetch (bypass the 6-hour cache)
pdga-ratings --pdga 12345 --refresh
```

**GUI**
```bash
pdga-ratings-gui
```

## Package layout

```
ratings_calculator/
├── cache.py       # SQLite cache (~/.pdga_ratings_cache.db), 6hr TTL
├── scraper.py     # HTTP fetching + HTML parsing
├── calculator.py  # Pure rating math — no I/O, fully unit-testable
├── cli.py         # argparse entrypoint + rich output
└── gui.py         # CustomTkinter desktop app

tests/
├── test_calculator.py  # Unit tests — no network, fast
├── test_scraper.py     # Smoke tests against real PDGA pages (slow)
└── test_history.py     # Math validation against real rating history (slow)
```

## Running tests

```bash
# Fast unit tests (no network required)
pytest tests/test_calculator.py -v

# Smoke tests — hits the real PDGA site (~30s)
pytest tests/test_scraper.py -v --timeout=60

# History math validation (~2min)
pytest tests/test_history.py -v --timeout=120

# Everything
pytest -v
```

### Maintaining the test player roster

`tests/test_scraper.py` and `tests/test_history.py` contain player rosters
with `TODO` placeholders. Fill these in with PDGA numbers you can personally
verify fit the described profile (active player, league-only, infrequent, etc.).
Your own number is a good starting point.

## How the math works

Per the [PDGA FAQ](https://www.pdga.com/faq/ratings):

1. Collect all rounds in the **12 months prior to the most recently rated round**.
   If fewer than 8 rounds exist, extend to **24 months**.
2. Drop outlier rounds below `max(avg − 100, avg − 2.5σ)`.
3. **Double-weight** the top 25% of remaining rounds.
4. Average all rounds (including the doubled top quartile).

Results are cached in `~/.pdga_ratings_cache.db` and expire after 6 hours.

## Roadmap

### Simulation & planning

- **Multi-update lookahead** — project what your rating will be at the next 2, 3, or 4 monthly updates, not just the next one. Would account for rounds aging out at each future cutoff and let you see a trajectory rather than a single snapshot.

- **Extended target solver** — the current solver answers "what do I need to average over N rounds to hit X rating at the *next* update?" This would extend it further out: "what do I need to average by the August update to hit X?" Useful for players with a season goal who want to plan their summer schedule.

- **"What's my floor?"** — given your current round set, what's the worst your rating can drop even if you play poorly for the rest of the window? Useful for players who are worried about a bad stretch.

- **Tournament impact preview** — before entering an event, show how a range of performances (e.g. 880–960) would affect your rating. Essentially a what-if slider scoped to a single upcoming tournament.

### History & visualization

- **Rating history chart** — line graph of your rating over time, pulled from the history page. The data is already being scraped for the math validation tests.

- **Round distribution histogram** — see the spread of your round ratings at a glance. Makes it immediately obvious where your outlier cutoff sits relative to your typical performance.

- **Personal bests** — surface your highest ever rating, biggest single-update gain, longest streak of improvements, etc.

- **Outlier recovery tracker** — if you have a bad round currently being outlier-dropped, show exactly when it ages out of the window and how much you'd automatically gain back.

### Multi-player

- **Player comparison** — load two PDGA numbers side-by-side. Useful for tracking a rival or comparing within a club.

- **Group/club view** — enter a list of numbers and see everyone's projected changes at once. Good for league organizers or club captains who track a whole roster.

### Quality of life

- **Saved players** — remember a list of numbers you check frequently, so you don't have to re-enter them each time.

- **Export to CSV** — download your full round history with ratings for your own analysis.

- **Mobile-friendly web layout** — the Flask backend is already live; the frontend just needs a responsive pass for smaller screens.
