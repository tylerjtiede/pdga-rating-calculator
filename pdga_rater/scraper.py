"""
scraper.py
----------
All network I/O and HTML parsing. Every function returns plain dicts/primitives
so the rest of the codebase stays decoupled from BeautifulSoup.
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from . import cache as cache_mod

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "pdga-rating-calculator/1.0"})

MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds


class FetchError(Exception):
    """Raised when a URL cannot be fetched after all retries."""


class ParseError(Exception):
    """Raised when expected HTML structure is missing or malformed."""


def fetch_html(url: str, force_refresh: bool = False) -> str:
    """
    Return the raw HTML for url. Results are cached in SQLite.
    Set force_refresh=True to bypass the cache and re-fetch unconditionally.
    """
    if not force_refresh:
        cached = cache_mod.get(url)
        if cached is not None:
            return cached

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=15)
            response.raise_for_status()
            html = response.text
            cache_mod.set(url, html)
            return html
        except requests.RequestException as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)

    raise FetchError(
        f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_exc}"
    )


def _parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


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
        raise ParseError(f"Could not parse date '{date_str}': {e}")


# ---------------------------------------------------------------------------
# Player pages
# ---------------------------------------------------------------------------

def fetch_player_pages(pdga_number: str, force_refresh: bool = False) -> dict:
    """
    Fetch and parse all pages needed for a player.
    Returns a dict of parsed page docs keyed by page name.
    """
    base = f"https://www.pdga.com/player/{pdga_number}"
    pages = {
        "stats":   fetch_html(base,             force_refresh),
        "detail":  fetch_html(f"{base}/details", force_refresh),
        "history": fetch_html(f"{base}/history", force_refresh),
    }
    return {k: _parse(v) for k, v in pages.items()}


def scrape_current_rating(doc_stats: BeautifulSoup, doc_history: BeautifulSoup) -> int:
    """Extract the player's current official PDGA rating."""
    try:
        rating_li = doc_stats.find("li", class_="current-rating")
        if rating_li:
            text = rating_li.get_text(strip=True)
            match = re.search(r"Current Rating:(\d+)", text)
            if match:
                return int(match.group(1))

        # Fallback: pull from history table
        rating_table = doc_history.find("table", id="player-results-history")
        if rating_table:
            first_row = rating_table.find("tbody").find("tr")
            return int(first_row.find("td", class_="player-rating").get_text(strip=True))
    except (AttributeError, ValueError, TypeError) as e:
        raise ParseError(f"Could not parse current rating: {e}")

    raise ParseError("Could not find current rating on player page.")


def scrape_rating_history(doc_history: BeautifulSoup) -> list[dict]:
    """
    Parse the player history page into a list of rating update dicts.
    Each dict has: { date_str, timestamp, rating }
    Used for math validation tests.
    """
    results = []
    try:
        table = doc_history.find("table", id="player-results-history")
        if not table:
            return results
        for row in table.find("tbody").find_all("tr"):
            date_td   = row.find("td", class_="date-received")
            rating_td = row.find("td", class_="player-rating")
            if date_td and rating_td:
                date_str = date_td.get_text(strip=True)
                try:
                    ts = int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())
                    results.append({
                        "date_str":  date_str,
                        "timestamp": ts,
                        "rating":    int(rating_td.get_text(strip=True)),
                    })
                except (ValueError, AttributeError):
                    continue
    except AttributeError as e:
        raise ParseError(f"Could not parse rating history: {e}")
    return results


def scrape_detail_tournaments(doc_detail: BeautifulSoup) -> list[dict]:
    """Parse the player detail page into a list of rated round dicts."""
    tournaments = []
    try:
        for row in doc_detail.find_all("tr"):
            tournament_cell = row.find("td", class_="tournament")
            if not tournament_cell:
                continue

            tournament: dict = {}
            link = tournament_cell.find("a")
            if link:
                tournament["name"] = link.get_text(strip=True)
                tournament["link"] = link["href"]

            fields = {
                "tier":      "tier",
                "date":      "date",
                "division":  "division",
                "round":     "round tooltip",
                "score":     "score",
                "rating":    "round-rating",
                "evaluated": "evaluated",
                "included":  "included",
            }
            for key, class_name in fields.items():
                cell = row.find("td", class_=class_name)
                if cell:
                    tournament[key] = cell.get_text(strip=True)

            try:
                tournament["rating"]    = int(tournament["rating"])
                tournament["timestamp"] = parse_pdga_date(tournament["date"])
            except (KeyError, ValueError, ParseError):
                continue

            tournaments.append(tournament)
    except AttributeError as e:
        raise ParseError(f"Could not parse detail tournaments: {e}")
    return tournaments


def scrape_stats_tournaments(doc_stats: BeautifulSoup) -> list[dict]:
    """Parse the player stats page for recently played (unrated) tournaments."""
    tournaments = []
    try:
        for row in doc_stats.select("tbody tr"):
            tournament: dict = {}
            tournament_td = row.find("td", class_="tournament")
            if not tournament_td:
                continue

            for key, class_name in [
                ("place", "place"), ("points", "points"),
                ("tier", "tier"),   ("prize",  "prize"),
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
                except ParseError:
                    continue

            tournaments.append(tournament)
    except AttributeError as e:
        raise ParseError(f"Could not parse stats tournaments: {e}")
    return tournaments


def scrape_tournament_rounds(href_link: str, pdga_number: str,
                              force_refresh: bool = False) -> tuple[list[int], int, str, bool]:
    """
    Fetch a tournament result page and extract round ratings for a player.
    Returns (ratings, timestamp, date_str, is_league).
    """
    url = f"https://www.pdga.com{href_link}"
    try:
        doc = _parse(fetch_html(url, force_refresh))
        is_league = bool(
            doc.body.find_all("h4", string=re.compile(r".*League.*"), recursive=True)
        )
        date_el = doc.find(class_="tournament-date")
        if not date_el:
            raise ParseError(f"No tournament-date element found at {url}")
        date_str  = date_el.get_text(strip=True)
        timestamp = parse_pdga_date(date_str)

        ratings: list[int] = []
        for row in doc.find_all("tr"):
            pdga_td = row.find("td", class_="pdga-number")
            if pdga_td and pdga_td.get_text(strip=True) == pdga_number:
                for cell in row.find_all("td", class_="round-rating"):
                    text = cell.get_text(strip=True)
                    if text:
                        ratings.append(int(text))
                break

        return ratings, timestamp, date_str, is_league

    except (AttributeError, ValueError) as e:
        raise ParseError(f"Could not parse tournament page {url}: {e}")


# ---------------------------------------------------------------------------
# Ratings update schedule
# ---------------------------------------------------------------------------

SCHEDULE_URL = "https://www.pdga.com/faq/ratings/when-updated"


def scrape_ratings_schedule(force_refresh: bool = False) -> list[dict]:
    """Parse the PDGA ratings update schedule."""
    try:
        doc  = _parse(fetch_html(SCHEDULE_URL, force_refresh))
        table = doc.find("table")
        rows  = table.find("tbody").find_all("tr")
        schedule = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) == 2:
                try:
                    deadline    = int(datetime.strptime(cells[0].get_text(strip=True), "%B %d, %Y").timestamp())
                    publication = int(datetime.strptime(cells[1].get_text(strip=True), "%B %d, %Y").timestamp())
                    schedule.append({"deadline": deadline, "publication": publication})
                except ValueError:
                    continue
        return schedule
    except (AttributeError, TypeError) as e:
        raise ParseError(f"Could not parse ratings schedule: {e}")


# ---------------------------------------------------------------------------
# High-level: load all data for a player
# ---------------------------------------------------------------------------

def load_player_data(pdga_number: str, force_refresh: bool = False) -> dict:
    """
    Fetch and parse everything needed to compute a player's projected rating.
    Returns a dict with keys:
        current_rating, tournaments, tournaments_stats,
        next_update, doc_stats (for current-events parsing)
    """
    pages            = fetch_player_pages(pdga_number, force_refresh)
    ratings_schedule = scrape_ratings_schedule(force_refresh)

    current_rating    = scrape_current_rating(pages["stats"], pages["history"])
    tournaments       = scrape_detail_tournaments(pages["detail"])
    tournaments_stats = scrape_stats_tournaments(pages["stats"])

    now         = int(datetime.now().timestamp())
    next_update = next(
        (d["deadline"] for d in ratings_schedule if d["deadline"] > now), None
    )
    if next_update is None:
        raise ParseError("Could not determine next ratings update date from schedule.")

    # Resolve new (unrated) tournaments
    known_links      = {t["link"] for t in tournaments}
    new_raw          = [t for t in tournaments_stats if t.get("link") not in known_links]
    new_tournaments  = []

    for tournament in new_raw:
        try:
            ratings, timestamp, date_str, is_league = scrape_tournament_rounds(
                tournament["link"], pdga_number, force_refresh
            )
        except (FetchError, ParseError):
            continue
        if not ratings:
            continue
        for i, rating in enumerate(ratings):
            new_tournaments.append({
                **tournament,
                "rating":    rating,
                "round":     i + 1,
                "timestamp": timestamp,
                "date":      date_str,
            })

    # Currently-playing and recent events
    for li_class in ["current-events", "recent-events"]:
        li = pages["stats"].find("li", class_=li_class)
        if not li:
            continue
        for event in li.find_all("a"):
            link = event["href"]
            name = event.get_text(strip=True)
            try:
                ratings, timestamp, date_str, is_league = scrape_tournament_rounds(
                    link, pdga_number, force_refresh
                )
            except (FetchError, ParseError):
                continue
            if is_league and timestamp >= next_update:
                continue
            for i, rating in enumerate(ratings):
                new_tournaments.append({
                    "name":      name,
                    "rating":    rating,
                    "timestamp": timestamp,
                    "date":      date_str,
                    "round":     i + 1,
                })

    return {
        "pdga_number":      pdga_number,
        "current_rating":   current_rating,
        "tournaments":      tournaments,       # fully rated rounds from detail page
        "new_tournaments":  new_tournaments,   # unrated rounds not yet on detail page
        "next_update":      next_update,
    }
