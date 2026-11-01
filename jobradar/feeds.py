"""Turn #hiring post search results into Post records and matching jobs.

Input is JSON the agent produced from WebSearch results or from reading the user's
own browser. Every field is untrusted third-party text: we only extract structure
(hashtags, links, emails printed in the post) and never act on instructions in it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .filters import norm_words
from .models import Post

HASHTAG = re.compile(r"(?<![\w#])#([A-Za-z][A-Za-z0-9_]{1,40})")
URL = re.compile(r"https?://[^\s<>\"')\]]+")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
HIRING_HINT = re.compile(r"#hiring|we(?:'| a)re hiring|\bhiring\b|open role|looking for|join (?:our|my) team", re.I)


def parse_post(raw: dict, found_via: str = "websearch") -> Post | None:
    url = (raw.get("url") or "").strip()
    if not url.startswith("https://") or "linkedin.com" not in url:
        return None
    text = " ".join(str(raw.get(k) or "") for k in ("text", "snippet", "title")).strip()
    profile = (raw.get("author_profile_url") or "").strip()
    if profile and not re.match(r"^https://([a-z]{2,3}\.)?linkedin\.com/in/[^/?#]+/?$", profile):
        profile = ""   # only keep plain LinkedIn profile links
    return Post(
        url=url,
        author=(raw.get("author") or "").strip()[:120],
        author_headline=(raw.get("author_headline") or raw.get("headline") or "").strip()[:200],
        author_profile_url=profile,
        text=text[:5000],
        posted=(raw.get("posted") or None),
        found_via=found_via,
        hashtags=sorted({h.lower() for h in HASHTAG.findall(text)}),
        links=list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(text)))[:10],
        emails=list(dict.fromkeys(EMAIL.findall(text)))[:5],
    )


def post_matches(post: Post, cfg: dict) -> bool:
    """A post matches if it reads as hiring and mentions one of the roles."""
    if not HIRING_HINT.search(post.text):
        return False
    words = " " + " ".join(norm_words(post.text.replace("#", " "))) + " "
    tags = " ".join(post.hashtags)
    for role in cfg.get("search", {}).get("roles", []):
        need = [w for w in norm_words(role) if w != "senior"]
        if f" {' '.join(need)} " in words or "".join(need) in tags:
            return True
    return False


def load_posts(path: str | Path, found_via: str) -> list[Post]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("results", data) if isinstance(data, dict) else data
    posts = [parse_post(r, found_via) for r in items if isinstance(r, dict)]
    return [p for p in posts if p]


class PostStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.urls = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self.urls.add(json.loads(line)["url"].split("?")[0].rstrip("/"))
                except (json.JSONDecodeError, KeyError):
                    pass

    def add_new(self, posts: list[Post]) -> list[Post]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = []
        with open(self.path, "a", encoding="utf-8") as fh:
            for p in posts:
                key = p.url.split("?")[0].rstrip("/")
                if key in self.urls:
                    continue
                self.urls.add(key)
                fh.write(json.dumps(p.to_dict()) + "\n")
                new.append(p)
        return new
