"""Build search queries: ATS discovery via search engines, and LinkedIn #hiring posts.

job-radar never calls a search engine itself. It prints queries; the agent runs them
with its WebSearch tool and hands the results back to `ingest`. Browser mode gives
LinkedIn content-search URLs for the user's own logged-in browser (opt-in).
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

ATS_SITES = {
    "greenhouse": "(site:boards.greenhouse.io OR site:job-boards.greenhouse.io)",
    "lever": "site:jobs.lever.co",
    "ashby": "site:jobs.ashbyhq.com",
    "workday": "site:myworkdayjobs.com",
}


def role_hashtag(role: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9]", "", role.title())


def ats_discovery_queries(cfg: dict) -> list[dict]:
    s = cfg.get("search", {})
    places = s.get("locations", [])[:2] or [""]
    if s.get("remote_ok", True):
        places = places + ["remote"]
    out = []
    for role in s.get("roles", []):
        for place in places:
            for source, site in ATS_SITES.items():
                q = f'{site} "{role}" {place}'.strip()
                out.append({"kind": "ats", "source": source, "role": role, "place": place, "query": q})
    return out


def post_queries(cfg: dict) -> list[dict]:
    s, f = cfg.get("search", {}), cfg.get("feeds", {})
    places = f.get("place_hashtags", [])[:2]
    modes = f.get("mode_hashtags", ["#remote", "#hybrid"])
    extra = " ".join(f.get("extra_hashtags", []))
    out = []
    for role in s.get("roles", []):
        # Search engines rarely honour site:linkedin.com/posts; #hiring posts usually come back as the
        # poster's profile page with the post in the snippet, so search all of linkedin.com.
        base = f'site:linkedin.com "#hiring" ("{role}" OR "{role_hashtag(role)}")'
        for place in places:
            out.append({"kind": "post", "role": role, "query": f"{base} {place} {extra}".strip()})
        if modes:
            mode_or = " OR ".join(f'"{m}"' for m in modes)
            out.append({"kind": "post", "role": role, "query": f"{base} ({mode_or}) {extra}".strip()})
    return out


def browser_search_urls(cfg: dict) -> list[dict]:
    """LinkedIn content-search URLs for the user's own browser, newest posts from the past week."""
    s, f = cfg.get("search", {}), cfg.get("feeds", {})
    place = (f.get("place_hashtags") or [""])[0]
    out = []
    for role in s.get("roles", []):
        for extra in [place] + f.get("mode_hashtags", []):
            kw = f"#hiring {role_hashtag(role)} {extra}".strip()
            url = ("https://www.linkedin.com/search/results/content/?keywords=" + quote(kw)
                   + "&datePosted=%22past-week%22&sortBy=%22date_posted%22")
            out.append({"kind": "browser", "role": role, "keywords": kw, "url": url})
    return out


_GH = re.compile(r"^(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io$")


def board_from_url(url: str) -> dict | None:
    """Turn a posting URL from search results into a [[boards]] entry, or None."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme != "https":
        return None
    host = parts.netloc.lower()
    segs = [s for s in parts.path.split("/") if s]
    if _GH.match(host) and segs:
        if segs[0] == "embed":          # embedded boards name the company in ?for=<slug>
            m = re.search(r"(?:^|&)for=([A-Za-z0-9_-]+)", parts.query)
            return {"source": "greenhouse", "slug": m.group(1).lower()} if m else None
        return {"source": "greenhouse", "slug": segs[0].lower()}
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and segs:
        b = {"source": "lever", "slug": segs[0].lower()}
        if ".eu." in host:
            b["region"] = "eu"
        return b
    if host == "jobs.ashbyhq.com" and segs:
        return {"source": "ashby", "slug": segs[0]}
    m = re.match(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com$", host)
    if m and segs:
        site = segs[1] if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", segs[0]) and len(segs) > 1 else segs[0]
        return {"source": "workday", "careers_url": f"https://{host}/{site}"}
    return None


def boards_from_urls(urls: list[str]) -> list[dict]:
    seen, out = set(), []
    for u in urls:
        b = board_from_url(u)
        if not b:
            continue
        key = (b["source"], b.get("slug") or b.get("careers_url"))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out
