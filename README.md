# pdga-rater

Project your PDGA rating before the official monthly update.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

**CLI**
```bash
# Basic projection
pdga-rater --pdga 12345

# What-if: add hypothetical rounds
pdga-rater --pdga 12345 --whatif 950,960,970

# Target solver: what do I need to average to hit 950?
pdga-rater --pdga 12345 --target 950 --rounds 3

# Force re-fetch (bypass 6hr cache)
pdga-rater --pdga 12345 --refresh
```

**GUI**
```bash
pdga-rater-gui
```

## Package layout

```
pdga_rater/
├── cache.py       # SQLite cache with 6hr TTL
├── scraper.py     # HTTP fetching + HTML parsing
├── calculator.py  # Pure rating math (no I/O)
├── cli.py         # argparse + rich output
└── gui.py         # CustomTkinter desktop app

tests/
├── test_calculator.py  # Unit tests — no network needed
├── test_scraper.py     # Smoke tests against real PDGA pages
└── test_history.py     # Math validation against real rating history
```

## Running tests

```bash
# Fast unit tests only (no network)
pytest tests/test_calculator.py -v

# Smoke tests (hits PDGA website, ~30s)
pytest tests/test_scraper.py -v --timeout=60

# History math validation (hits PDGA website, ~2min)
pytest tests/test_history.py -v --timeout=120

# Everything
pytest -v
```

## How the math works

PDGA rating calculation per the [official FAQ](https://www.pdga.com/faq/ratings):

1. Collect all rounds in the 12 months prior to the most recently rated round.
   If fewer than 8 rounds exist in that window, extend to 24 months.
2. Drop outliers below `max(avg - 100, avg - 2.5σ)`.
3. Double-weight the top 25% of remaining rounds.
4. Average all rounds (including the doubled top quartile).

The cache lives at `~/.pdga_rater_cache.db` and expires entries after 6 hours.
