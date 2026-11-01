"""Shared records: a Job from any source, and a hiring Post from a LinkedIn feed."""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(value: str | None) -> str:
    """Strip tags and decode entities. Good enough for scoring; not a renderer."""
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"(?i)<\s*(br|/p|/li|/h\d)\s*/?>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str                      # greenhouse | lever | ashby | workday | linkedin | websearch | post
    location: str = ""
    work_mode: str = ""              # remote | hybrid | onsite | "" (unknown)
    posted: str | None = None        # YYYY-MM-DD when the source gives one
    description: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Post:
    """A public social post announcing a role (e.g. LinkedIn '#hiring')."""
    url: str
    author: str = ""                 # name as shown on the post
    author_headline: str = ""        # e.g. "Talent Acquisition at Acme"
    author_profile_url: str = ""     # only if visible on the post itself
    text: str = ""
    posted: str | None = None
    found_via: str = "websearch"     # websearch | browser
    hashtags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)   # links printed in the post body
    emails: list[str] = field(default_factory=list)  # emails printed in the post body only

    def to_dict(self) -> dict:
        return asdict(self)


def detect_work_mode(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    if re.search(r"\bhybrid\b", blob):
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh|anywhere)\b", blob):
        return "remote"
    if re.search(r"\b(on-?site|in-office|office-based)\b", blob):
        return "onsite"
    return ""
