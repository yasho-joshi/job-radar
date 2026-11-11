"""Bridge to the TypeScript LinkedIn public-jobs CLI in tools/linkedin-search (needs Bun).

Uses LinkedIn's public guest job listings only: no login. Keep volume low; automated
access is against LinkedIn's terms, so this is for personal use at a gentle pace.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import ROOT
from .models import Job, detect_work_mode

CLI = ROOT / "tools" / "linkedin-search" / "src" / "cli.ts"


def find_bun() -> str | None:
    bun = shutil.which("bun")
    if bun:
        return bun
    # winget installs Bun under the user's WinGet packages folder without updating PATH for old shells
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for p in local.glob("Oven-sh.Bun_*/**/bun.exe") if local.exists() else []:
        return str(p)
    home_bun = Path.home() / ".bun" / "bin" / ("bun.exe" if os.name == "nt" else "bun")
    return str(home_bun) if home_bun.exists() else None


def search(query: str, location: str, jobage: int = 14, limit: int = 20,
           jobage_minutes: int | None = None) -> list[Job]:
    bun = find_bun()
    if not bun:
        raise RuntimeError("Bun is not installed; see README (winget install Oven-sh.Bun)")
    age = ["--jobage-minutes", str(jobage_minutes)] if jobage_minutes else ["--jobage", str(jobage)]
    cmd = [bun, "run", str(CLI), "search", "-q", query, "-l", location,
           *age, "-n", str(limit), "--format", "json"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[:300] or "linkedin-search failed")
    data = json.loads(res.stdout or "{}")
    jobs = []
    for r in data.get("results", []):
        jobs.append(Job(
            title=r.get("title", ""), company=r.get("company", ""), url=r.get("url", ""),
            source="linkedin", location=r.get("location", ""),
            work_mode="remote" if location.lower() == "remote" else detect_work_mode(r.get("location", "")),
            posted=r.get("date"), extra={"linkedin_id": r.get("id")},
        ))
    return jobs


def search_all(cfg: dict, pause: float = 1.0, state=None,
               ok: list[str] | None = None) -> tuple[list[Job], list[str]]:
    """Run every role x location query. With a ScanState, each query asks only for jobs posted since
    its own last successful run; keys of queries that succeeded are appended to `ok`."""
    from .state import linkedin_key, window_minutes
    li, roles = cfg.get("linkedin", {}), cfg.get("search", {}).get("roles", [])
    days = li.get("jobage_days", 14)
    jobs, errors = [], []
    for role in roles:
        for loc in li.get("locations", []):
            key = linkedin_key(role, loc)
            minutes = window_minutes(state.since(key), days) if state else None
            try:
                jobs += search(role, loc, days, li.get("limit_per_query", 20), jobage_minutes=minutes)
                if ok is not None:
                    ok.append(key)
            except Exception as e:  # one failed query never sinks the run
                errors.append(f"linkedin '{role}' @ {loc}: {e}")
            time.sleep(pause)
    return jobs, errors
