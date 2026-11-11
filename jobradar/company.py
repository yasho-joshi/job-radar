"""Company quality from AmbitionBox research the agent gathered (data/company_research/<company>.json).

The agent reads a company's AmbitionBox overview, reviews (newest first) and salary pages and writes
what it saw under the "ambitionbox" key. This module never fetches anything. It enforces the rules
in code so they do not depend on the agent: only reviews from the last 30 days count, scores come
from a fixed formula, and the recommendation follows fixed thresholds.

Research shape (fields the agent could not see are left out, never guessed):
{
  "company": "Acme",
  "ambitionbox": {
    "fetched_date": "2026-11-10", "status": "ok" | "blocked" | "not_found", "url": "...",
    "overall_rating": 3.9, "review_count": 1234,
    "category_ratings": {"work_life_balance": 3.8, "salary": 3.6, "job_security": 3.4,
                         "career_growth": 3.5, "skill_development": 3.7, "work_satisfaction": 3.5,
                         "company_culture": 3.7},
    "salary": {"role": "Senior Product Manager", "min_lpa": 30, "avg_lpa": 45, "max_lpa": 70,
               "data_points": 120},
    "recent_reviews": [{"date": "2026-11-02", "rating": 4, "positives": ["..."], "negatives": ["..."]}],
    "summary": {"sentiment": "...", "outlook": "...", "strengths": [], "green_flags": [],
                "red_flags": [], "risks": [{"text": "...", "severity": "high" | "medium" | "low"}]}
  }
}
Reviews are stored as short themes in the agent's own words: no reviewer names, no copied review text.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import DATA
from .dedup import norm_company

RESEARCH = DATA / "company_research"
REVIEW_WINDOW_DAYS = 30
MIN_RECENT_REVIEWS = 3


def research_path(company: str) -> Path:
    return RESEARCH / f"{norm_company(company) or 'unknown'}.json"


def load_research(company: str) -> dict:
    p = research_path(company)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def research_age_days(research: dict, today: date | None = None) -> int | None:
    ab = research.get("ambitionbox") or {}
    try:
        return ((today or date.today()) - date.fromisoformat(ab["fetched_date"])).days
    except (KeyError, ValueError, TypeError):
        return None


def needs_research(company: str, max_age_days: int, today: date | None = None) -> bool:
    age = research_age_days(load_research(company), today)
    return age is None or age > max_age_days


def _to100(rating: float | None) -> float | None:
    if rating is None:
        return None
    return max(0.0, min(100.0, (float(rating) - 1) / 4 * 100))


def recent_reviews(ab: dict, today: date | None = None) -> list[dict]:
    """Reviews dated within the last 30 days; undated or older reviews are dropped."""
    cutoff = (today or date.today()) - timedelta(days=REVIEW_WINDOW_DAYS)
    out = []
    for r in ab.get("recent_reviews") or []:
        try:
            d = date.fromisoformat(str(r.get("date", ""))[:10])
        except ValueError:
            continue
        if d >= cutoff and r.get("rating") is not None:
            out.append(r)
    return out


def salary_check(ab: dict, floor_lpa: float | None) -> str:
    s = ab.get("salary") or {}
    lo, avg, hi = s.get("min_lpa"), s.get("avg_lpa"), s.get("max_lpa")
    if hi is None and avg is None:
        return "no salary data"
    if floor_lpa is None:
        return "no floor set"
    if hi is not None and hi < floor_lpa:
        return f"below floor: range tops out at {hi} LPA (floor {floor_lpa})"
    if avg is not None and avg < floor_lpa:
        return f"floor reachable only above the average ({avg} LPA avg, floor {floor_lpa})"
    return f"meets floor ({lo if lo is not None else '?'}-{hi if hi is not None else '?'} LPA)"


def assess(research: dict, today: date | None = None, floor_lpa: float | None = None) -> dict:
    """Company quality 0-100 and Apply / Consider / Avoid. Returns quality None when there is no data."""
    ab = research.get("ambitionbox") or {}
    notes: list[str] = []
    if ab.get("status") != "ok" or ab.get("overall_rating") is None:
        why = {"blocked": "AmbitionBox blocked the fetch", "not_found": "company not on AmbitionBox"}.get(
            ab.get("status"), "no AmbitionBox research yet")
        return {"quality": None, "recommendation": "Consider", "notes": [why],
                "recent_review_count": 0, "recent_avg": None, "salary": salary_check(ab, floor_lpa)}

    overall = _to100(ab["overall_rating"])
    recent = recent_reviews(ab, today)
    recent_avg = round(sum(float(r["rating"]) for r in recent) / len(recent), 2) if recent else None
    if len(recent) >= MIN_RECENT_REVIEWS:
        recent_score = _to100(recent_avg)
    else:
        recent_score = overall
        notes.append(f"only {len(recent)} review(s) in the last {REVIEW_WINDOW_DAYS} days; used the overall rating")
    cats = [v for v in (ab.get("category_ratings") or {}).values() if isinstance(v, (int, float))]
    cat_score = _to100(sum(cats) / len(cats)) if cats else overall

    score = 0.35 * overall + 0.40 * recent_score + 0.25 * cat_score
    if len(recent) >= MIN_RECENT_REVIEWS:
        trend = (recent_avg - float(ab["overall_rating"])) * 10          # +/-1 star -> +/-10 points
        score += max(-10.0, min(10.0, trend))
        if trend <= -3:
            notes.append(f"recent reviews ({recent_avg}) trail the overall rating ({ab['overall_rating']})")
    risks = (ab.get("summary") or {}).get("risks") or []
    high = sum(1 for r in risks if str(r.get("severity", "")).lower() == "high")
    medium = sum(1 for r in risks if str(r.get("severity", "")).lower() == "medium")
    score -= min(20, 8 * high + 3 * medium)
    quality = int(round(max(0.0, min(100.0, score))))

    if quality < 50 or high >= 2:
        rec = "Avoid"
    elif quality >= 70 and high == 0:
        rec = "Apply"
    else:
        rec = "Consider"
    sal = salary_check(ab, floor_lpa)
    if sal.startswith("below floor") and rec == "Apply":
        rec = "Consider"
        notes.append("salary estimate is below your floor")
    return {"quality": quality, "recommendation": rec, "notes": notes, "recent_review_count": len(recent),
            "recent_avg": recent_avg, "salary": sal, "high_risks": high}
