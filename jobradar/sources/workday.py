"""Workday public CXS endpoint (no auth).

careers_url  https://<tenant>.wd<N>.myworkdayjobs.com[/<locale>]/<site>
search       POST https://<host>/wday/cxs/<tenant>/<site>/jobs  {"searchText": ..., "limit": 20, "offset": n}
detail       GET  https://<host>/wday/cxs/<tenant>/<site><externalPath>

Workday only gives a relative "Posted N Days Ago" label, so `posted` is derived from it.
Detail pages are fetched only for jobs that pass the caller's filters (see fetch_details).
"""

from __future__ import annotations

import re
import time
from datetime import date, timedelta
from urllib.parse import urlsplit

from ..http import fetch_json
from ..models import Job, detect_work_mode, html_to_text

URL_RE = re.compile(r"^https://(?P<tenant>[a-z0-9-]+)\.(?P<inst>wd\d+)\.myworkdayjobs\.com"
                    r"(?:/(?P<locale>[a-z]{2}-[A-Z]{2}))?/(?P<site>[^/?#]+)", re.I)
PAGE = 20
MAX_PAGES = 10          # 200 postings per search is plenty for a keyword search
PAGE_DELAY = 0.3


def parse_careers_url(url: str) -> dict:
    m = URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a Workday careers URL: {url}")
    host = urlsplit(url).netloc
    return {"host": host, "tenant": m["tenant"], "site": m["site"]}


def posted_from_label(label: str, today: date | None = None) -> str | None:
    today = today or date.today()
    s = (label or "").lower()
    if "today" in s:
        return today.isoformat()
    if "yesterday" in s:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*\+?\s*days?", s)
    if m and "+" not in s:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None  # "30+ Days Ago" is unbounded: don't guess


def fetch(board: dict, query: str = "") -> list[Job]:
    ep = parse_careers_url(board["careers_url"])
    company = board.get("name") or ep["tenant"]
    api = f"https://{ep['host']}/wday/cxs/{ep['tenant']}/{ep['site']}/jobs"
    jobs: list[Job] = []
    for page in range(MAX_PAGES):
        data = fetch_json(api, {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE,
                                "searchText": query or ""})
        postings = data.get("jobPostings") or []
        for p in postings:
            path = p.get("externalPath")
            if not path:
                continue
            loc = p.get("locationsText") or ""
            jobs.append(Job(
                title=(p.get("title") or "").strip(), company=company,
                url=f"https://{ep['host']}/{ep['site']}{path}", source="workday",
                location=loc, work_mode=detect_work_mode(loc, p.get("title", "")),
                posted=posted_from_label(p.get("postedOn", "")),
                extra={"api_detail": f"https://{ep['host']}/wday/cxs/{ep['tenant']}/{ep['site']}{path}"},
            ))
        total = data.get("total") or 0
        if len(postings) < PAGE or (page + 1) * PAGE >= total:
            break
        time.sleep(PAGE_DELAY)
    return jobs


MAX_DETAILS = 60


def fetch_details(jobs: list[Job]) -> list[str]:
    """Fill description, full location list and work mode for Workday jobs in place.

    Search results say "2 Locations" for multi-city roles, so the real cities only
    come from the detail call. Capped at MAX_DETAILS requests per run.
    """
    errors = []
    todo = [j for j in jobs if j.source == "workday" and j.extra.get("api_detail") and not j.description]
    for job in todo[:MAX_DETAILS]:
        try:
            info = (fetch_json(job.extra["api_detail"]) or {}).get("jobPostingInfo") or {}
        except Exception as e:
            errors.append(f"workday detail {job.url}: {e}")
            continue
        locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
        if any(locs):
            job.location = " / ".join(dict.fromkeys(l for l in locs if l))
        job.description = html_to_text(info.get("jobDescription"))
        remote = (info.get("remoteType") or "").lower()
        job.work_mode = ("remote" if "remote" in remote else "hybrid" if "hybrid" in remote
                         else job.work_mode or detect_work_mode(job.location, job.description[:2000]))
        time.sleep(PAGE_DELAY)
    if len(todo) > MAX_DETAILS:
        errors.append(f"workday: only the first {MAX_DETAILS} of {len(todo)} detail pages fetched")
    return errors
