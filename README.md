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
