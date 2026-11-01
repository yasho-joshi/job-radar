"""Cross-source de-duplication and the seen-jobs store (data/seen.jsonl).

The same role often appears on LinkedIn, the company's ATS and a #hiring post.
A job is a duplicate if its canonical URL or its (company, title) key was seen before.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Job

COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|pvt|private|plc|gmbh|ag|sa|bv|corp|corporation|co|technologies|"
    r"technology|labs|india|group|holdings)\b\.?", re.I)
TRACKING = re.compile(r"^(utm_|gh_src|ref|src|source|trk|trackingid|refid|lever-source|lever-origin)", re.I)


def norm_company(name: str) -> str:
    s = COMPANY_SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", "", s)


def norm_title(title: str) -> str:
    s = (title or "").lower()
    s = re.sub(r"\bsr\.?\b", "senior", s)
    s = re.sub(r"\((?:m/f/d|f/m/d|m/w/d|all genders|remote|hybrid|on-?site)\)", " ", s)
    s = re.sub(r"\s\|\s.*$", "", s)                     # drop " | Bengaluru"; keep " - Payments" (a real team)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)]
    host = p.netloc.lower()
    host = re.sub(r"^[a-z]{2}\.linkedin\.com$", "www.linkedin.com", host)
    path = p.path.rstrip("/")
    m = re.search(r"/jobs/view/(?:[^/]*-)?(\d{6,})$", path)
    if "linkedin.com" in host and m:
        path, q = f"/jobs/view/{m.group(1)}", []
    return urlunsplit(("https", host, path, urlencode(q), ""))


def job_key(company: str, title: str) -> str:
    return hashlib.sha1(f"{norm_company(company)}|{norm_title(title)}".encode()).hexdigest()[:16]


class SeenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.urls: set[str] = set()
        self.keys: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.urls.add(row.get("url", ""))
                self.keys.add(row.get("key", ""))

    def split(self, jobs: list[Job]) -> tuple[list[Job], list[Job]]:
        """Return (new, duplicates). Also de-dupes within the batch, preferring ATS over aggregators."""
        rank = {"greenhouse": 0, "lever": 0, "ashby": 0, "workday": 0, "post": 1, "linkedin": 2, "websearch": 3}
        ordered = sorted(jobs, key=lambda j: rank.get(j.source, 9))
        new, dupes, batch_urls, batch_keys = [], [], set(), set()
        for j in ordered:
            url, key = canonical_url(j.url), job_key(j.company, j.title)
            if url in self.urls or key in self.keys or url in batch_urls or key in batch_keys:
                dupes.append(j)
                continue
            batch_urls.add(url)
            batch_keys.add(key)
            j.extra["key"] = key
            new.append(j)
        return new, dupes

    def record(self, jobs: list[Job], status: str = "new") -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with open(self.path, "a", encoding="utf-8") as fh:
            for j in jobs:
                url, key = canonical_url(j.url), job_key(j.company, j.title)
                if url in self.urls or key in self.keys:
                    continue
                fh.write(json.dumps({"key": key, "url": url, "title": j.title, "company": j.company,
                                     "source": j.source, "location": j.location, "posted": j.posted,
                                     "first_seen": date.today().isoformat(), "status": status}) + "\n")
                self.urls.add(url)
                self.keys.add(key)
                n += 1
        return n
