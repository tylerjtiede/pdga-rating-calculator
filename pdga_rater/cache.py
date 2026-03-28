"""
cache.py
--------
SQLite-backed cache for PDGA page responses.
Entries expire after CACHE_TTL_HOURS and are transparently re-fetched.
"""

import sqlite3
import time
from pathlib import Path

CACHE_TTL_HOURS = 6
CACHE_TTL_SECS = CACHE_TTL_HOURS * 3600
DB_PATH = Path.home() / ".pdga_rater_cache.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_cache (
            url       TEXT PRIMARY KEY,
            html      TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def get(url: str) -> str | None:
    """Return cached HTML for url if it exists and hasn't expired, else None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT html, fetched_at FROM page_cache WHERE url = ?", (url,)
        ).fetchone()
    if row is None:
        return None
    html, fetched_at = row
    if time.time() - fetched_at > CACHE_TTL_SECS:
        return None  # expired — caller will re-fetch and store
    return html


def set(url: str, html: str) -> None:
    """Store HTML for url with the current timestamp."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO page_cache (url, html, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET html=excluded.html, fetched_at=excluded.fetched_at
            """,
            (url, html, int(time.time())),
        )
        conn.commit()


def invalidate(url: str) -> None:
    """Force-expire a single cached entry."""
    with _connect() as conn:
        conn.execute("DELETE FROM page_cache WHERE url = ?", (url,))
        conn.commit()


def invalidate_player(pdga_number: str) -> None:
    """Force-expire all cached pages for a given PDGA number."""
    with _connect() as conn:
        conn.execute(
            "DELETE FROM page_cache WHERE url LIKE ?", (f"%/{pdga_number}%",)
        )
        conn.commit()


def clear_all() -> None:
    """Wipe the entire cache."""
    with _connect() as conn:
        conn.execute("DELETE FROM page_cache")
        conn.commit()


def cache_info() -> list[dict]:
    """Return metadata about all cached entries (for debugging/display)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT url, fetched_at FROM page_cache ORDER BY fetched_at DESC"
        ).fetchall()
    now = time.time()
    return [
        {
            "url": url,
            "fetched_at": fetched_at,
            "age_minutes": round((now - fetched_at) / 60, 1),
            "expired": (now - fetched_at) > CACHE_TTL_SECS,
        }
        for url, fetched_at in rows
    ]
