"""Greenhouse public Job Board API (no auth): boards-api.greenhouse.io/v1/boards/<slug>/jobs."""

from __future__ import annotations

from ..http import fetch_json
from ..models import Job, detect_work_mode, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def fetch(board: dict, query: str = "") -> list[Job]:
    slug = board["slug"]
    company = board.get("name") or slug
    data = fetch_json(API.format(slug=slug))
    jobs = []
    for j in data.get("jobs", []):
        url = j.get("absolute_url")
        if not url:
            continue
        location = (j.get("location") or {}).get("name", "")
        desc = html_to_text(j.get("content"))
        posted = (j.get("first_published") or j.get("updated_at") or "")[:10] or None
        jobs.append(Job(
            title=j.get("title", "").strip(), company=company, url=url, source="greenhouse",
            location=location, work_mode=detect_work_mode(location, j.get("title", "")),
            posted=posted, description=desc, extra={"board": slug, "id": j.get("id")},
        ))
    return jobs
