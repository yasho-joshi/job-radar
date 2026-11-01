"""Ashby public posting API (no auth): api.ashbyhq.com/posting-api/job-board/<slug>."""

from __future__ import annotations

from ..http import fetch_json
from ..models import Job, detect_work_mode, html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def fetch(board: dict, query: str = "") -> list[Job]:
    slug = board["slug"]
    company = board.get("name") or slug
    data = fetch_json(API.format(slug=slug), timeout=40.0)  # Ashby is slow by design
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        url = j.get("jobUrl")
        if not url:
            continue
        locs = [j.get("location") or ""] + [
            (s or {}).get("location", "") for s in j.get("secondaryLocations") or []]
        location = " / ".join(dict.fromkeys(l for l in locs if l))
        # workplaceType is the reliable field; isRemote alone mislabels hybrid roles.
        wt = (j.get("workplaceType") or "").lower()
        mode = wt if wt in ("remote", "hybrid") else ("onsite" if wt == "onsite" else "")
        if not mode and j.get("isRemote") is True:
            mode = "remote"
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        jobs.append(Job(
            title=(j.get("title") or "").strip(), company=company, url=url, source="ashby",
            location=location, work_mode=mode or detect_work_mode(location),
            posted=(j.get("publishedAt") or "")[:10] or None,
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            extra={"board": slug, "compensation": comp},
        ))
    return jobs
