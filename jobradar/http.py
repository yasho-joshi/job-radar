"""Tiny stdlib HTTP helper: JSON GET/POST with a timeout, polite retries and a size cap."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "job-radar/0.1 (+personal job search; low volume)"
MAX_BYTES = 20 * 1024 * 1024  # never read more than 20 MB from one response
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{status or 'error'} for {url}: {message}")
        self.url = url
        self.status = status


def _request(url: str, data: bytes | None, headers: dict[str, str], timeout: float) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise FetchError(url, resp.status, "response too large")
        return body


def fetch_json(url: str, payload: dict | None = None, *, timeout: float = 20.0,
               retries: int = 2, backoff: float = 1.5, extra_headers: dict | None = None):
    """GET (or POST when payload is given) a URL and parse JSON. Retries 429/5xx and timeouts."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    attempt = 0
    while True:
        try:
            return json.loads(_request(url, data, headers, timeout).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < retries:
                attempt += 1
                time.sleep(backoff ** attempt)
                continue
            raise FetchError(url, e.code, e.reason) from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                attempt += 1
                time.sleep(backoff ** attempt)
                continue
            raise FetchError(url, None, str(getattr(e, "reason", e))) from None
        except json.JSONDecodeError:
            raise FetchError(url, None, "response was not JSON") from None
