"""Incremental crawl state (data/scan_state.json).

Each source query (one ATS board, one LinkedIn role x location) keeps the start time of its last
successful fetch. The next run asks only for what was posted since then (LinkedIn's minute-level
window) or drops postings dated before that day (ATS boards, which return the whole board and
date postings to the day). A source that failed keeps its old watermark, so nothing is skipped.
The seen-jobs store still removes anything that slips through twice.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OVERLAP = timedelta(minutes=60)      # re-ask for the last hour too: listings index late


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def board_key(b: dict) -> str:
    return f"{b.get('source')}:{b.get('slug') or b.get('careers_url')}"


def linkedin_key(role: str, location: str) -> str:
    return f"linkedin:{role}@{location}"


class ScanState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = {"sources": {}, "last_success": None}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass                        # a corrupt file means a full (3-day) scan, never a crash

    def since(self, key: str) -> datetime | None:
        v = self.data["sources"].get(key)
        try:
            return datetime.fromisoformat(v) if v else None
        except ValueError:
            return None

    def mark(self, keys: list[str], started: datetime) -> None:
        for k in keys:
            self.data["sources"][k] = started.isoformat()
        self.data["last_success"] = started.isoformat()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")


def window_minutes(since: datetime | None, max_days: int, now: datetime | None = None) -> int | None:
    """LinkedIn freshness window in minutes: time since the last success plus overlap, capped at max_days.
    None means no previous run: use the plain max_days window."""
    if since is None:
        return None
    gap = (now or now_utc()) - since + OVERLAP
    return max(60, min(math.ceil(gap.total_seconds() / 60), max_days * 1440))


def posted_since(posted: str | None, since: datetime | None) -> bool:
    """ATS postings carry a day, not a time: keep anything dated on or after the last success's day."""
    if since is None or not posted:
        return True
    try:
        return date.fromisoformat(posted[:10]) >= since.date()
    except ValueError:
        return True
