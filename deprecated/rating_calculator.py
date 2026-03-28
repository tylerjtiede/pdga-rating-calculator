"""
PDGA Rating Calculator
----------------------
Scrapes your PDGA profile and computes your projected rating for the next update.

Usage:
    python rating_calculator.py --pdga 12345
    python rating_calculator.py --pdga 12345 --whatif 950,960,970
"""

import re
import argparse
from datetime import datetime
from operator import itemgetter

import numpy as np
import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="PDGA rating calculator")
    parser.add_argument("--pdga", type=str, required=True, help="PDGA number")
    parser.add_argument(
        "--whatif",
        type=str,
        required=False,
        help="Comma-separated hypothetical round ratings, e.g. 950,960",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "pdga-rating-calculator/1.0"})

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds


def fetch(url: str) -> BeautifulSoup:
    """Fetch a URL with retries and return a BeautifulSoup doc."""
    import time

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=15)
            response.raise_for_status()
            return BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {e}")
            console.print(f"[yellow]Request failed (attempt {attempt}/{MAX_RETRIES}), retrying...[/yellow]")
            time.sleep(RETRY_BACKOFF * attempt)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def parse_pdga_date(date_str: str) -> int:
    """Parse a PDGA date string and return a Unix timestamp."""
    if "Date:" in date_str:
        date_str = date_str.split("Date: ")[1]
    try:
        if "to" in date_str:
            _, end_part = date_str.split("to")
            dt = datetime.strptime(end_part.strip(), "%d-%b-%Y")
        else:
            dt = datetime.strptime(date_str.strip(), "%d-%b-%Y")
        return int(dt.timestamp())
    except Exception as e:
        raise ValueError(f"Could not parse date '{date_str}': {e}")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_current_rating(doc_stats: BeautifulSoup, doc_history: BeautifulSoup) -> int:
    """Extract the player's current official rating."""
    rating_li = doc_stats.find("li", class_="current-rating")
    if rating_li:
        text = rating_li.get_text(strip=True)
        return int(re.search(r"Current Rating:(\d+)", text).group(1))

    # Fallback: pull from history table
    rating_table = doc_history.find("table", id="player-results-history")
    first_row = rating_table.find("tbody").find("tr")
    return int(first_row.find("td", class_="player-rating").get_text(strip=True))


def scrape_ratings_schedule(doc_updates: BeautifulSoup) -> list[dict]:
    """Parse the PDGA ratings update schedule into a list of deadline/publication dicts."""
    table = doc_updates.find("table")
    rows = table.find("tbody").find_all("tr")
    schedule = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) == 2:
            deadline = int(datetime.strptime(cells[0].get_text(strip=True), "%B %d, %Y").timestamp())
            publication = int(datetime.strptime(cells[1].get_text(strip=True), "%B %d, %Y").timestamp())
            schedule.append({"deadline": deadline, "publication": publication})
    return schedule


def scrape_detail_tournaments(doc_detail: BeautifulSoup) -> list[dict]:
    """Parse the player detail page into a list of rated round dicts."""
    tournaments = []
    for row in doc_detail.find_all("tr"):
        tournament_cell = row.find("td", class_="tournament")
        if not tournament_cell:
            continue

        tournament = {}

        link = tournament_cell.find("a")
        if link:
            tournament["name"] = link.get_text(strip=True)
            tournament["link"] = link["href"]

        fields = {
            "tier": "tier",
            "date": "date",
            "division": "division",
            "round": "round tooltip",
            "score": "score",
            "rating": "round-rating",
            "evaluated": "evaluated",
            "included": "included",
        }
        for key, class_name in fields.items():
            cell = row.find("td", class_=class_name)
            if cell:
                tournament[key] = cell.get_text(strip=True)

        try:
            tournament["rating"] = int(tournament["rating"])
            tournament["timestamp"] = parse_pdga_date(tournament["date"])
        except (KeyError, ValueError):
            continue

        tournaments.append(tournament)
    return tournaments


def scrape_stats_tournaments(doc_stats: BeautifulSoup) -> list[dict]:
    """Parse the player stats page for recently played tournaments."""
    tournaments = []
    for row in doc_stats.select("tbody tr"):
        tournament = {}

        tournament_td = row.find("td", class_="tournament")
        if not tournament_td:
            continue

        for key, class_name in [
            ("place", "place"),
            ("points", "points"),
            ("tier", "tier"),
            ("prize", "prize"),
        ]:
            cell = row.find("td", class_=class_name)
            if cell:
                tournament[key] = cell.get_text(strip=True)

        link_tag = tournament_td.find("a")
        if link_tag:
            tournament["name"] = link_tag.get_text(strip=True)
            tournament["link"] = link_tag["href"].split("#")[0]

        dates_cell = row.find("td", class_="dates")
        if dates_cell:
            tournament["date"] = dates_cell.get_text(strip=True)
            try:
                tournament["timestamp"] = parse_pdga_date(tournament["date"])
            except ValueError:
                continue

        tournaments.append(tournament)
    return tournaments


def scrape_tournament_rounds(href_link: str, pdga_number: str) -> tuple[list[int], int, str, bool]:
    """
    Fetch a tournament page and return:
        (ratings, timestamp, date_str, is_league)
    """
    doc = fetch(f"https://www.pdga.com{href_link}")
    is_league = bool(
        doc.body.find_all("h4", string=re.compile(r".*League.*"), recursive=True)
    )
    date_str = doc.find(class_="tournament-date").get_text(strip=True)
    timestamp = parse_pdga_date(date_str)

    ratings = []
    for row in doc.find_all("tr"):
        pdga_td = row.find("td", class_="pdga-number")
        if pdga_td and pdga_td.get_text(strip=True) == pdga_number:
            for cell in row.find_all("td", class_="round-rating"):
                text = cell.get_text(strip=True)
                if text:
                    ratings.append(int(text))
            break

    return ratings, timestamp, date_str, is_league


# ---------------------------------------------------------------------------
# Rating calculation (pure, testable)
# ---------------------------------------------------------------------------

ONE_YEAR_SECS = 365 * 24 * 60 * 60
TWO_YEARS_SECS = 2 * ONE_YEAR_SECS
MIN_ROUNDS_FOR_ONE_YEAR = 8


def compute_lookback_window(rounds: list[dict]) -> tuple[int, int]:
    """
    Determine the lookback start timestamp per PDGA rules:
      - Use 12 months back from the most recent rated round.
      - If fewer than 8 rounds exist in that window, extend to 24 months.

    Returns (most_recent_timestamp, last_date).
    """
    if not rounds:
        raise ValueError("No rounds provided to compute lookback window.")

    most_recent = max(r["timestamp"] for r in rounds)
    last_date = most_recent - ONE_YEAR_SECS

    rounds_in_window = [r for r in rounds if r["timestamp"] > last_date]
    if len(rounds_in_window) < MIN_ROUNDS_FOR_ONE_YEAR:
        last_date = most_recent - TWO_YEARS_SECS

    return most_recent, last_date


def compute_pdga_rating(ratings: list[int]) -> tuple[int, float]:
    """
    Compute the projected PDGA rating and outlier cutoff from a list of round ratings.
    Returns (projected_rating, drop_below_cutoff).
    """
    avg = np.average(ratings)
    drop_below = float(np.round(max(avg - 100, avg - 2.5 * np.std(ratings))))
    ratings_filtered = [r for r in ratings if r >= drop_below]

    doubled = ratings_filtered[: len(ratings_filtered) // 4]

    if len(ratings_filtered) < 8:
        projected = round(np.average(ratings_filtered))
    else:
        projected = round(np.average(ratings_filtered + doubled))

    return projected, drop_below


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(
    projected_rating: int,
    current_rating: int,
    drop_below: float,
    outgoing_rounds: list[dict],
    incoming_rounds: list[dict],
    outlier_rounds: list[dict],
):
    rating_change = projected_rating - current_rating
    change_color = "green" if rating_change >= 0 else "red"

    console.print()
    console.print(
        f"[bold]Projected rating:[/bold] [bold cyan]{projected_rating}[/bold cyan] "
        f"([{change_color}]{rating_change:+}[/{change_color}])"
    )
    console.print(f"[bold]Outlier cutoff:[/bold] {drop_below}")
    console.print()

    def make_table(title: str, rounds: list[dict]) -> Table:
        table = Table(title=title, box=box.SIMPLE_HEAD, show_lines=False)
        table.add_column("Tournament", style="dim", no_wrap=False)
        table.add_column("Rd", justify="right")
        table.add_column("Rating", justify="right")
        for rd in rounds:
            rating_val = rd["rating"]
            rating_str = f"[red]{rating_val}[/red]" if rating_val < drop_below else str(rating_val)
            table.add_row(rd.get("name", "?"), str(rd.get("round", "?")), rating_str)
        return table

    if outgoing_rounds:
        console.print(make_table("Rounds Dropping Off", outgoing_rounds))
    else:
        console.print("[dim]No rounds dropping off.[/dim]")

    console.print()

    if incoming_rounds:
        console.print(make_table("Rounds Coming In", incoming_rounds))
    else:
        console.print("[dim]No new rounds coming in.[/dim]")

    console.print()

    if outlier_rounds:
        console.print(make_table("Outlier Rounds (excluded)", outlier_rounds))
    else:
        console.print("[green]No outlier rounds.[/green]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    pdga_number = args.pdga

    with console.status("Fetching player data..."):
        doc_detail = fetch(f"https://www.pdga.com/player/{pdga_number}/details")
        doc_stats = fetch(f"https://www.pdga.com/player/{pdga_number}")
        doc_history = fetch(f"https://www.pdga.com/player/{pdga_number}/history")
        doc_updates = fetch("https://www.pdga.com/faq/ratings/when-updated")

    current_rating = scrape_current_rating(doc_stats, doc_history)
    ratings_schedule = scrape_ratings_schedule(doc_updates)
    tournaments = scrape_detail_tournaments(doc_detail)
    tournaments_stats = scrape_stats_tournaments(doc_stats)

    # Determine next update deadline
    now = int(datetime.now().timestamp())
    next_update = next(
        (d["deadline"] for d in ratings_schedule if d["deadline"] > now), None
    )
    if next_update is None:
        raise RuntimeError("Could not determine next ratings update date.")

    # Find new tournaments (on stats page but not yet rated on detail page)
    known_links = {t["link"] for t in tournaments}
    new_tournaments_raw = [t for t in tournaments_stats if t.get("link") not in known_links]

    new_tournaments = []
    with console.status("Fetching new tournament data..."):
        for tournament in new_tournaments_raw:
            ratings, timestamp, date_str, is_league = scrape_tournament_rounds(
                tournament["link"], pdga_number
            )
            if not ratings:
                continue  # DNF or no rating yet
            for i, rating in enumerate(ratings):
                entry = {**tournament, "rating": rating, "round": i + 1, "timestamp": timestamp, "date": date_str}
                new_tournaments.append(entry)

        # Check currently-playing and recent events
        now_playing_li = doc_stats.find("li", class_="current-events")
        recent_events_li = doc_stats.find("li", class_="recent-events")
        event_links = []
        if now_playing_li:
            event_links += now_playing_li.find_all("a")
        if recent_events_li:
            event_links += recent_events_li.find_all("a")

        for event in event_links:
            link = event["href"]
            name = event.get_text(strip=True)
            ratings, timestamp, date_str, is_league = scrape_tournament_rounds(link, pdga_number)
            if is_league and timestamp >= next_update:
                continue
            for i, rating in enumerate(ratings):
                new_tournaments.append({
                    "name": name,
                    "rating": rating,
                    "timestamp": timestamp,
                    "date": date_str,
                    "round": i + 1,
                })

    # Handle --whatif
    if args.whatif:
        fake_ratings = args.whatif.split(",")[::-1]
        for i, rd in enumerate(fake_ratings):
            entry = {
                "name": f"Hypothetical Round {i + 1}",
                "rating": int(rd),
                "timestamp": now,
                "round": i + 1,
            }
            new_tournaments.append(entry)

    # Bug fix 1: anchor lookback to most recent rated round, not next update deadline.
    #            Also handles the <8 rounds -> extend to 24 months rule.
    # Bug fix 2: respect included == 'Yes' so rounds PDGA already dropped as outliers
    #            aren't re-counted in our calculation.
    all_candidate_rounds = new_tournaments + [
        t for t in tournaments if t.get("evaluated") == "Yes"
    ]
    _, last_date = compute_lookback_window(all_candidate_rounds)

    used_rounds = new_tournaments + [
        t for t in tournaments
        if t.get("evaluated") == "Yes"
        and t["timestamp"] > last_date
        and t.get("included") == "Yes"
    ]

    sorted_rounds = sorted(used_rounds, key=itemgetter("timestamp"), reverse=True)
    ratings_list = [t["rating"] for t in sorted_rounds]

    projected_rating, drop_below = compute_pdga_rating(ratings_list)

    outgoing_rounds = [
        t for t in tournaments
        if t.get("evaluated") == "Yes" and t["timestamp"] <= last_date
    ]
    incoming_rounds = sorted(
        new_tournaments, key=lambda x: (x.get("timestamp", 0), x.get("round", 0))
    )
    outlier_rounds = [r for r in used_rounds if r["rating"] < drop_below]

    print_results(projected_rating, current_rating, drop_below, outgoing_rounds, incoming_rounds, outlier_rounds)


if __name__ == "__main__":
    main()
