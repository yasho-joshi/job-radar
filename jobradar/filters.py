"""Decide whether a job matches the user's roles, places, work modes and freshness."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .models import Job

ABBREV = {"sr": "senior", "snr": "senior", "mgr": "manager", "pm": "product manager",
          "tpm": "technical product manager", "po": "product owner", "jr": "junior"}
STOP = {"of", "and", "the", "a", "an", "-", "/", "&"}


def norm_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9+#]+", (text or "").lower())
    out: list[str] = []
    for w in words:
        out.extend(ABBREV.get(w, w).split())
    return [w for w in out if w not in STOP]


def title_matches(title: str, roles: list[str], exclude: list[str] = ()) -> bool:
    t = " " + " ".join(norm_words(title)) + " "
    if any(f" {' '.join(norm_words(x))} " in t for x in exclude if x.strip()):
        return False
    for role in roles:
        # The role must appear as a phrase ("product manager", not "product marketing
        # manager"). "senior" is optional so "Product Manager III" still matches.
        need = [w for w in norm_words(role) if w != "senior"]
        if need and f" {' '.join(need)} " in t:
            return True
    return False


def location_matches(job: Job, search: dict) -> bool:
    places = [p.lower() for p in search.get("locations", []) + search.get("also_accept", [])]
    loc = (job.location or "").lower()
    if any(p in loc for p in places):
        return True
    modes = search.get("work_modes", ["remote", "hybrid", "onsite"])
    if job.work_mode and job.work_mode not in modes:
        return False
    if not search.get("remote_ok", True):
        return False
    if job.work_mode != "remote" and not re.search(r"\b(remote|anywhere|worldwide|global)\b", loc):
        return False
    if re.search(r"\b(anywhere|worldwide|global)\b", loc):
        return True
    # "US - Remote", "Remote, Canada": remote but tied to a place the user did not list -> reject.
    leftover = re.sub(r"\b(remote|hybrid|work from home|wfh|fully|first|only|based)\b", " ", loc)
    leftover = re.sub(r"[^a-z]+", " ", leftover).strip()
    return not leftover


def fresh_enough(job: Job, max_age_days: int | None, today: date | None = None) -> bool:
    if not max_age_days or not job.posted:
        return True  # unknown dates are kept and flagged downstream, never guessed
    try:
        posted = date.fromisoformat(job.posted[:10])
    except ValueError:
        return True
    return posted >= (today or date.today()) - timedelta(days=max_age_days)


def by_title(jobs: list[Job], cfg: dict) -> list[Job]:
    s = cfg.get("search", {})
    return [j for j in jobs if title_matches(j.title, s.get("roles", []), s.get("exclude_titles", []))]


ATS_SOURCES = {"greenhouse", "lever", "ashby", "workday"}


def max_age_for(job: Job, search: dict) -> int | None:
    # A company's own ATS only lists open roles, and its date is when the posting was created,
    # so an older date there is still a live opening. Aggregators and posts go stale faster.
    if job.source in ATS_SOURCES:
        return search.get("ats_max_age_days", 60)
    return search.get("max_age_days")


def apply(jobs: list[Job], cfg: dict) -> list[Job]:
    s = cfg.get("search", {})
    return [j for j in by_title(jobs, cfg)
            if location_matches(j, s) and fresh_enough(j, max_age_for(j, s))]
