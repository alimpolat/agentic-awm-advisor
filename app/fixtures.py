"""Shared fixture loader for the POC agents.

All file I/O is cached at process level with lru_cache so repeated calls
within a single run are free. BeautifulSoup strips HTML to collapsed plain text.

Cache-safety note
-----------------
load_portfolio and load_meeting_notes return MUTABLE objects (dict / list).
To avoid cache-poisoning across agents that run concurrently under asyncio.gather,
the lru_cache is applied to an inner function that caches the raw text / tuple;
the public functions return a FRESH object on every call.
"""
import json
from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup

_DATA = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _portfolio_raw(client_id: str) -> str:
    """Cache the raw JSON text (immutable str) so disk I/O happens only once."""
    return (_DATA / f"{client_id}_portfolio.json").read_text(encoding="utf-8")


def load_portfolio(client_id: str = "bergstrom") -> dict:
    """Return the portfolio JSON for client_id as a FRESH plain dict each call."""
    return json.loads(_portfolio_raw(client_id))


# ---------------------------------------------------------------------------
# IPS text — str is immutable, lru_cache is safe
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def load_ips_text(client_id: str = "bergstrom") -> str:
    """Return the IPS HTML converted to collapsed plain text."""
    html = (_DATA / "corpus" / f"{client_id}_ips.html").read_text(encoding="utf-8")
    return _html_text(html)


# ---------------------------------------------------------------------------
# Meeting notes
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _meeting_notes_tuple(client_id: str) -> tuple[str, ...]:
    """Cache the parsed notes as an immutable tuple so disk I/O happens only once."""
    pattern = f"{client_id}_meeting_notes_*.html"
    paths = sorted((_DATA / "corpus").glob(pattern))
    return tuple(_html_text(p.read_text(encoding="utf-8")) for p in paths)


def load_meeting_notes(client_id: str = "bergstrom") -> list[str]:
    """Return all meeting notes for client_id, sorted by filename (chronological), as plain text.

    Each element of the returned list corresponds to one note file.
    Returns a FRESH list each call to prevent cache-poisoning.
    """
    return list(_meeting_notes_tuple(client_id))


def save_meeting_note(client_id: str, text: str) -> Path:
    """Persist a new advisor meeting note and invalidate the notes cache so the
    next brief generation includes it. Returns the written file path.

    Notes are stored as the same HTML-wrapped format the loader expects, with a
    UTC-timestamped filename so they sort chronologically after the seeded notes.
    User text is HTML-escaped on write; the loader strips tags on read.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    safe = escape((text or "").strip())
    path = _DATA / "corpus" / f"{client_id}_meeting_notes_{ts}.html"
    path.write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(client_id)} meeting notes {ts}</title></head><body>"
        '<div class="eyebrow">AWM &middot; Advisory meeting notes (advisor capture)</div>'
        f'<div class="meta">Date {ts} &middot; Captured via the after-meeting panel</div>'
        f"<p>{safe}</p></body></html>",
        encoding="utf-8",
    )
    _meeting_notes_tuple.cache_clear()
    return path


def _html_text(html: str) -> str:
    """Strip HTML tags and collapse all whitespace to single spaces."""
    return " ".join(BeautifulSoup(html, "html.parser").get_text(separator=" ").split())
