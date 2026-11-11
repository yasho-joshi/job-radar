"""Shortlist: ranked jobs with match > min_match, joined with company quality, minus applications
already made. Top N by 0.7 x match + 0.3 x quality (weights in search.toml [shortlist]).

The match score is the existing /rank score (0.30 technical + 0.25 experience + 0.15 behavioral +
0.30 career), read unchanged from data/seen.jsonl. Company quality comes from jobradar.company.

Duplicate applications are found three ways:
  1. data/seen.jsonl status "applied";
  2. data/tracker.csv rows (any status but "drafted") with the same URL or the same company + title;
  3. data/gmail_checks.json, written from the agent's read-only Gmail search (`--gmail-in`):
     "applied_same_role" excludes the job, "applied_company" keeps it with a flag.
"""

from __future__ import annotations

import csv
import html
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import company
from .config import DATA, ROOT
from .dedup import canonical_url, job_key

GMAIL = DATA / "gmail_checks.json"
TRACKER = DATA / "tracker.csv"
GMAIL_STATUSES = {"applied_same_role", "applied_company", "none"}
GMAIL_RECHECK_DAYS = 1
DEFAULTS = {"min_match": 80, "top_n": 5, "match_weight": 0.7, "quality_weight": 0.3,
            "salary_floor_lpa": None, "research_max_age_days": 7}
NO_DATA_QUALITY = 50          # neutral stand-in so a job without company data is neither boosted nor buried


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **cfg.get("shortlist", {})}


def _rows() -> list[dict]:
    p = DATA / "seen.jsonl"
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _tracker_applied() -> tuple[set[str], set[str]]:
    urls, keys = set(), set()
    if TRACKER.exists():
        with open(TRACKER, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("status") or "").strip() in ("", "drafted"):
                    continue
                if r.get("job_url"):
                    urls.add(canonical_url(r["job_url"]))
                keys.add(job_key(r.get("company", ""), (r.get("role") or "").replace(";", ",")))
    return urls, keys


def load_gmail() -> dict:
    try:
        return json.loads(GMAIL.read_text(encoding="utf-8")) if GMAIL.exists() else {}
    except json.JSONDecodeError:
        return {}


def merge_gmail(path: str | Path, today: date | None = None) -> int:
    """Store the agent's Gmail findings: [{"key", "status", "evidence"}]. Evidence is a subject line
    and date only, never message bodies."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    store = load_gmail()
    n = 0
    for r in data:
        if r.get("key") and r.get("status") in GMAIL_STATUSES:
            store[r["key"]] = {"checked": (today or date.today()).isoformat(), "status": r["status"],
                               "evidence": str(r.get("evidence", ""))[:200]}
            n += 1
    GMAIL.parent.mkdir(parents=True, exist_ok=True)
    GMAIL.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding="utf-8")
    return n


def _gmail_fresh(entry: dict | None, today: date) -> bool:
    try:
        return bool(entry) and date.fromisoformat(entry["checked"]) >= today - timedelta(days=GMAIL_RECHECK_DAYS)
    except (KeyError, ValueError):
        return False


def eligible(cfg: dict, today: date | None = None) -> tuple[list[dict], list[dict]]:
    """(candidates above the match bar, duplicates found locally or in Gmail)."""
    today = today or date.today()
    s = settings(cfg)
    t_urls, t_keys = _tracker_applied()
    gmail = load_gmail()
    cands, dupes = [], []
    for r in _rows():
        score = r.get("score", r.get("rank_score"))
        if r.get("status") not in ("ranked", "applied") or not isinstance(score, (int, float)):
            continue
        if score <= s["min_match"]:
            continue
        key = r.get("key") or job_key(r.get("company", ""), r.get("title", ""))
        item = {"key": key, "title": r.get("title", ""), "company": r.get("company", ""),
                "location": r.get("location", ""), "url": r.get("url", ""),
                "official_url": r.get("official_url") or r.get("url", ""), "posted": r.get("posted"),
                "match": score, "verdict": r.get("verdict", r.get("rank_verdict", "")),
                "strengths": r.get("strengths", []), "gaps": r.get("gaps", []), "flags": []}
        g = gmail.get(key)
        if r.get("status") == "applied":
            item["duplicate"] = "marked applied in data/seen.jsonl"
        elif canonical_url(item["url"]) in t_urls or key in t_keys:
            item["duplicate"] = "already in data/tracker.csv"
        elif g and g.get("status") == "applied_same_role":
            item["duplicate"] = f"Gmail: {g.get('evidence') or 'application email found'}"
        if item.get("duplicate"):
            dupes.append(item)
            continue
        if g and g.get("status") == "applied_company":
            item["flags"].append(f"applied to {item['company']} before (Gmail: {g.get('evidence', '')})")
        item["gmail_checked"] = _gmail_fresh(g, today)
        item["research_needed"] = company.needs_research(item["company"], s["research_max_age_days"], today)
        cands.append(item)
    return cands, dupes


def build(cfg: dict, today: date | None = None) -> dict:
    today = today or date.today()
    s = settings(cfg)
    cands, dupes = eligible(cfg, today)
    for c in cands:
        a = company.assess(company.load_research(c["company"]), today, s["salary_floor_lpa"])
        c["company_quality"] = a
        q = a["quality"] if a["quality"] is not None else NO_DATA_QUALITY
        c["final"] = round(s["match_weight"] * c["match"] + s["quality_weight"] * q, 1)
        if a["quality"] is None:
            c["flags"].append(a["notes"][0])
        if not c["gmail_checked"]:
            c["flags"].append("Gmail not checked")
        if a["recommendation"] == "Avoid":
            c["flags"].append("company recommendation: Avoid")
    # "Avoid" companies sort below everything else; they are shown, never silently hidden
    cands.sort(key=lambda c: (c["company_quality"]["recommendation"] != "Avoid", c["final"]), reverse=True)
    top = cands[: s["top_n"]]
    for i, c in enumerate(top, 1):
        c["pick"] = i
    return {"generated": datetime.now().isoformat(timespec="minutes"), "settings": s, "top": top,
            "below_cut": cands[s["top_n"]:], "duplicates": dupes}


def latest_path() -> Path | None:
    files = sorted((DATA / "runs").glob("*-shortlist.json"))
    return files[-1] if files else None


def write(result: dict) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M")
    js = DATA / "runs" / f"{stamp}-shortlist.json"
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    page = ROOT / "output" / "shortlist" / f"{stamp}.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render_html(result), encoding="utf-8")
    return js, page


def _li(items) -> str:
    return "".join(f"<li>{html.escape(str(x))}</li>" for x in items or [])


def render_html(result: dict) -> str:
    e = html.escape
    cards = []
    for c in result["top"]:
        q = c["company_quality"]
        summ = (company.load_research(c["company"]).get("ambitionbox") or {}).get("summary") or {}
        risks = [f"{r.get('text', '')} ({r.get('severity', '?')})" for r in summ.get("risks") or []]
        cmd = f"py -m jobradar apply shortlist --pick {c['pick']}"
        url = c["official_url"] if c["official_url"].startswith("https://") else c["url"]
        cards.append(f"""
<article>
 <header><span class="pick">#{c['pick']}</span><h2>{e(c['title'])}</h2>
  <span class="rec rec-{e(q['recommendation'].lower())}">{e(q['recommendation'])}</span></header>
 <p class="meta">{e(c['company'])} · {e(c['location'] or '?')} · posted {e(str(c['posted'] or '?'))}</p>
 <p class="scores"><b>{c['final']}</b> final · match {c['match']} · company {q['quality'] if q['quality'] is not None else 'n/a'}
  · {q['recent_review_count']} reviews in 30 days · salary: {e(q['salary'])}</p>
 {f'<p class="flags">{e(" | ".join(c["flags"]))}</p>' if c['flags'] else ''}
 <details><summary>Company: sentiment, outlook, flags</summary>
  <p><b>Sentiment:</b> {e(summ.get('sentiment', 'n/a'))}</p><p><b>Outlook:</b> {e(summ.get('outlook', 'n/a'))}</p>
  <div class="cols"><div><b>Strengths</b><ul>{_li(summ.get('strengths'))}</ul><b>Green flags</b><ul>{_li(summ.get('green_flags'))}</ul></div>
  <div><b>Red flags</b><ul>{_li(summ.get('red_flags'))}</ul><b>Risks</b><ul>{_li(risks)}</ul></div></div>
 </details>
 <details><summary>Fit: strengths and gaps</summary><ul>{_li(c['strengths'])}</ul><b>Gaps</b><ul>{_li(c['gaps'])}</ul></details>
 <div class="actions">
  <a class="btn" href="{e(url)}" target="_blank" rel="noopener noreferrer">Apply: open careers page</a>
  <button class="btn ghost" data-cmd="{e(cmd)}">Copy assisted-apply command</button>
 </div>
</article>""")
    dupes = "".join(f"<li>{e(d['title'])} | {e(d['company'])}: {e(d['duplicate'])}</li>" for d in result["duplicates"])
    body = "".join(cards) or "<p>No job is above the match bar right now.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Job Shortlist</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1c1c1c;--muted:#666;--line:#e3e3df;--accent:#1f6feb;--good:#1a7f37;--warn:#9a6700;--bad:#cf222e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--card:#1b1b1b;--ink:#eee;--muted:#aaa;--line:#333;--accent:#58a6ff;--good:#3fb950;--warn:#d29922;--bad:#f85149}}}}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:860px;margin:auto}} article{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}}
header{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} h2{{font-size:17px;margin:0;flex:1}}
.pick{{color:var(--muted);font-weight:600}} .meta,.scores{{margin:6px 0;color:var(--muted)}} .scores b{{color:var(--ink);font-size:17px}}
.flags{{color:var(--warn);margin:6px 0}} .rec{{padding:2px 10px;border-radius:99px;font-weight:600;font-size:13px;border:1px solid}}
.rec-apply{{color:var(--good)}} .rec-consider{{color:var(--warn)}} .rec-avoid{{color:var(--bad)}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}} summary{{cursor:pointer;margin:6px 0}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}} .btn{{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 14px;text-decoration:none;font:inherit;cursor:pointer}}
.btn.ghost{{background:transparent;color:var(--accent);border:1px solid var(--accent)}}
</style></head><body><main>
<h1>Job shortlist</h1>
<p class="meta">{e(result['generated'])} · match above {result['settings']['min_match']} · final = {result['settings']['match_weight']} x match + {result['settings']['quality_weight']} x company quality.
Triage scores: check each posting yourself. The assisted-apply command fills the form in a browser and stops for your review; nothing is submitted until you confirm.</p>
{body}
<h3>Excluded as already applied</h3><ul>{dupes or '<li>None</li>'}</ul>
</main><script>
document.querySelectorAll('[data-cmd]').forEach(b=>b.addEventListener('click',async()=>{{
 try{{await navigator.clipboard.writeText(b.dataset.cmd);b.textContent='Copied: paste in your terminal'}}catch(e){{b.textContent=b.dataset.cmd}}}}));
</script></body></html>"""
