"""Per-site knowledge: which URLs, where the form is, what success and 'closed' look like."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Site:
    name: str
    host_re: str
    submit_re: str
    success_re: str
    closed_re: str
    next_re: str = ""            # multi-step flows (LinkedIn Easy Apply)
    root: str = ""               # CSS selector of the container holding the form
    max_per_run: int = 10
    delay: tuple[int, int] = (20, 45)

    def apply_url(self, url: str) -> str:
        u = url.split("?")[0].rstrip("/")
        if self.name == "lever":
            return u if u.endswith("/apply") else u + "/apply"
        if self.name == "ashby":
            return u if u.endswith("/application") else u + "/application"
        return url


SUCCESS_COMMON = r"thank(s| you) for (applying|your application)|application (has been |was )?(received|submitted|sent)|we('| ha)ve received your application"
CLOSED_COMMON = r"no longer (accepting|available|open)|job (has been|is) (closed|filled)|position (has been )?filled|this job (posting )?(has )?expired|page (you were looking for )?(was )?not found"

SITES = {
    "greenhouse": Site("greenhouse", r"^(job-)?boards(\.eu)?\.greenhouse\.io$", r"^submit( application)?$",
                       SUCCESS_COMMON, CLOSED_COMMON),
    "lever": Site("lever", r"^jobs(\.eu)?\.lever\.co$", r"^submit application$", SUCCESS_COMMON, CLOSED_COMMON),
    "ashby": Site("ashby", r"^jobs\.ashbyhq\.com$", r"^submit application$", SUCCESS_COMMON, CLOSED_COMMON),
    "linkedin": Site("linkedin", r"^([a-z]{2,3}\.)?linkedin\.com$", r"^submit application$",
                     r"application (was )?sent|your application was sent|applied", CLOSED_COMMON,
                     next_re=r"^(next|continue( to next step)?|review( your application)?)$",
                     root='[role="dialog"]', max_per_run=5, delay=(60, 120)),
}

CAPTCHA_VISIBLE_JS = r"""
() => [...document.querySelectorAll('iframe')].some(f => {
  const s = (f.src || '') + ' ' + (f.title || '');
  if (!/recaptcha\/api2\/bframe|recaptcha\/enterprise\/bframe|hcaptcha.*challenge|challenge.*hcaptcha|turnstile|arkose|funcaptcha/i.test(s)) return false;
  const r = f.getBoundingClientRect(); const st = getComputedStyle(f);
  return r.width > 60 && r.height > 60 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
})
"""


def detect(url: str) -> Site | None:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return None
    for site in SITES.values():
        if re.match(site.host_re, host):
            if site.name == "linkedin" and "/jobs/view/" not in url:
                return None
            return site
    return None


def blocked_reason(page) -> str | None:
    """Login walls, checkpoints and challenges mean: stop and hand back to the user."""
    url = page.url.lower()
    if any(s in url for s in ("/checkpoint", "/authwall", "/login", "/uas/login", "challenge")):
        return "login or security checkpoint"
    try:
        if page.evaluate(CAPTCHA_VISIBLE_JS):
            return "CAPTCHA challenge"
    except Exception:
        pass
    return None


def page_says(page, pattern: str) -> bool:
    try:
        return bool(re.search(pattern, page.inner_text("body", timeout=5000), re.I))
    except Exception:
        return False
