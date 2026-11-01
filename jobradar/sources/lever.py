"""Lever public Postings API (no auth): api.lever.co/v0/postings/<slug>?mode=json (EU: api.eu.lever.co)."""

from __future__ import annotations

from datetime import datetime, timezone

from ..http import fetch_json
from ..models import Job, detect_work_mode, html_to_text

API = "https://{host}/v0/postings/{slug}?mode=json&limit={limit}&skip={skip}"
PAGE = 100
MAX_PAGES = 30          # 3,000 postings; aggregators like Jobgether run boards bigger than one response should be


def fetch(board: dict, query: str = "") -> list[Job]:
    slug = board["slug"]
    host = "api.eu.lever.co" if board.get("region") == "eu" else "api.lever.co"
    company = board.get("name") or slug
    data: list = []
    for page in range(MAX_PAGES):
        try:
            chunk = fetch_json(API.format(host=host, slug=slug, limit=PAGE, skip=page * PAGE))
        except Exception:
            if page == 0:
                raise
            board["_partial"] = f"stopped after {len(data)} postings (page {page + 1} failed)"
            break      # keep the pages we already have rather than losing the whole board
        if not isinstance(chunk, list):
            break
        data += chunk
        if len(chunk) < PAGE:
            break
    jobs = []
    for j in data:
        url = j.get("hostedUrl")
        if not url:
            continue
        cats = j.get("categories") or {}
        locs = [cats.get("location") or ""] + [l for l in cats.get("allLocations") or [] if l]
        location = " / ".join(dict.fromkeys(l for l in locs if l))
        created = j.get("createdAt")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                  if isinstance(created, (int, float)) else None)
        wt = (j.get("workplaceType") or "").lower()
        mode = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(wt, "")
        desc = j.get("descriptionPlain") or ""
        for block in j.get("lists") or []:
            desc += f"\n{block.get('text', '')}\n" + (block.get("content") or "")
        jobs.append(Job(
            title=(j.get("text") or "").strip(), company=company, url=url, source="lever",
            location=location, work_mode=mode or detect_work_mode(location),
            posted=posted, description=html_to_text(desc), extra={"board": slug, "id": j.get("id")},
        ))
    return jobs
