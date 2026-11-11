"""Command line: python -m jobradar <command> [options]. Run with --help for details."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import feeds, filters, linkedin, outreach, queries
from .config import DATA, load
from .dedup import SeenStore
from .models import Job
from .sources import REGISTRY, workday
from .state import ScanState, board_key, now_utc, posted_since


def _jobs_out(jobs: list[Job], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([j.to_dict() for j in jobs], indent=1, ensure_ascii=False), encoding="utf-8")


def _summary(jobs: list[Job]) -> None:
    for j in jobs:
        print(f"  [{j.source:10}] {j.title} | {j.company} | {j.location or '?'} | {j.work_mode or '?'} | {j.posted or 'date ?'}")


def fetch_boards(boards: list[dict], cfg: dict, state: ScanState | None = None,
                 ok: list[str] | None = None) -> tuple[list[Job], list[str]]:
    """Fetch boards. With a ScanState, postings dated before a board's last successful run are
    dropped (incremental); keys of boards fetched without error are appended to `ok`."""
    jobs, errors = [], []
    roles = cfg["search"].get("roles", [])
    for b in boards:
        mod = REGISTRY.get(b.get("source"))
        if not mod:
            errors.append(f"unknown source in board: {b}")
            continue
        try:
            got = []
            if b["source"] == "workday":
                # Workday's search box is a plain keyword search, so run one search per role.
                for role in roles or [""]:
                    got += mod.fetch(b, role)
            else:
                got += mod.fetch(b)    # these APIs return the whole board; filters do the matching
            since = state.since(board_key(b)) if state else None
            jobs += [j for j in got if posted_since(j.posted, since)]
            if b.get("_partial"):
                errors.append(f"{b['source']} {b.get('slug')}: partial board, {b.pop('_partial')}")
            elif ok is not None:
                ok.append(board_key(b))  # a partial board keeps its old watermark so nothing is skipped
        except Exception as e:
            errors.append(f"{b.get('source')} {b.get('slug') or b.get('careers_url')}: {e}")
    return jobs, errors


def cmd_scan(a) -> int:
    cfg = load(a.config)
    started = now_utc()
    state = ScanState(DATA / "scan_state.json") if a.incremental else None
    ok: list[str] = []
    all_jobs, errors = [], []
    if not a.no_boards:
        got, err = fetch_boards(cfg["boards"], cfg, state, ok)
        all_jobs += got
        errors += err
    if a.linkedin:
        got, err = linkedin.search_all(cfg, state=state, ok=ok)
        all_jobs += got
        errors += err
    store = SeenStore(DATA / "seen.jsonl")
    titled = filters.by_title(all_jobs, cfg)
    unseen = [j for j in titled if not store.has(j)]  # never re-fetch details for jobs already processed
    errors += workday.fetch_details(unseen)           # real locations for "2 Locations" rows
    matched = filters.apply(unseen, cfg)
    new, dupes = store.split(matched)
    stamp = started.astimezone().strftime("%Y-%m-%dT%H%M") if a.incremental else date.today().isoformat()
    out = Path(a.out or DATA / "runs" / f"{stamp}-scan.json")
    if new or not a.incremental:                      # hourly runs with nothing new leave no empty run file
        _jobs_out(new, out)
    if not a.dry_run:
        store.record(new)
        if state is not None:
            state.mark(ok, started)
            state.save()
    print(f"config: {cfg['_path']}")
    mode = "incremental" if a.incremental else "full window"
    print(f"{mode} | fetched {len(all_jobs)} | already processed {len(titled) - len(unseen)} | "
          f"matched {len(matched)} | new {len(new)} | duplicates in batch {len(dupes)}")
    _summary(new)
    for e in errors:
        print(f"  ! {e}", file=sys.stderr)
    print(f"new jobs written to {out}" if (new or not a.incremental) else "no new jobs since the last run")
    return 0


def cmd_queries(a) -> int:
    cfg = load(a.config)
    kinds = {"ats": queries.ats_discovery_queries, "posts": queries.post_queries,
             "browser": queries.browser_search_urls}
    print(json.dumps(kinds[a.kind](cfg), indent=1, ensure_ascii=False))
    return 0


def cmd_discover(a) -> int:
    """Search-result URLs -> new [[boards]] entries (+ optionally scan them now)."""
    cfg = load(a.config)
    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    urls = [d["url"] if isinstance(d, dict) else d for d in (data.get("results", data) if isinstance(data, dict) else data)]
    known = {(b.get("source"), b.get("slug") or b.get("careers_url")) for b in cfg["boards"]}
    found = [b for b in queries.boards_from_urls(urls)
             if (b["source"], b.get("slug") or b.get("careers_url")) not in known]
    print(f"{len(found)} new boards from {len(urls)} URLs")
    for b in found:
        print("\n[[boards]]\n" + "\n".join(f'{k} = "{v}"' for k, v in b.items()))
    if a.scan and found:
        got, errors = fetch_boards(found, cfg)
        titled = filters.by_title(got, cfg)
        errors += workday.fetch_details(titled)
        matched = filters.apply(titled, cfg)
        store = SeenStore(DATA / "seen.jsonl")
        new, _ = store.split(matched)
        out = Path(a.out or DATA / "runs" / f"{date.today().isoformat()}-discover.json")
        _jobs_out(new, out)
        if not a.dry_run:
            store.record(new)
        print(f"\nscanned discovered boards: matched {len(matched)} | new {len(new)} -> {out}")
        _summary(new)
        for e in errors:
            print(f"  ! {e}", file=sys.stderr)
    return 0


def cmd_posts(a) -> int:
    cfg = load(a.config)
    posts = feeds.load_posts(a.input, a.via)
    matched = [p for p in posts if feeds.post_matches(p, cfg)]
    new = feeds.PostStore(DATA / "posts.jsonl").add_new(matched) if not a.dry_run else matched
    boards = queries.boards_from_urls([u for p in matched for u in p.links])
    print(f"posts read {len(posts)} | hiring + role match {len(matched)} | new {len(new)}")
    for p in new:
        who = p.author or "unknown author"
        print(f"  - {who} ({p.author_headline or 'no headline'}) {p.url}")
        if p.emails:
            print(f"      emails printed in post: {', '.join(p.emails)}")
        if p.links:
            print(f"      links in post: {', '.join(p.links[:3])}")
    if boards:
        print(f"\nATS boards linked from posts (add with `discover`): {json.dumps(boards)}")
    return 0


def cmd_record(a) -> int:
    rows = json.loads(Path(a.input).read_text(encoding="utf-8"))
    jobs = [Job(**{k: r.get(k) for k in Job.__dataclass_fields__ if k in r}) for r in rows]
    n = SeenStore(DATA / "seen.jsonl").record(jobs, a.status)
    print(f"recorded {n} jobs as {a.status}")
    return 0


def cmd_outreach_page(a) -> int:
    out, problems = outreach.write_page(a.input, a.out)
    print(f"wrote {out}")
    for p in problems:
        print(f"  ! {p}")
    return 1 if problems and a.strict else 0


def cmd_apply(a) -> int:
    try:
        from .apply import runner
    except ImportError:
        print("Playwright is not installed: py -m pip install playwright && py -m playwright install chromium")
        return 1
    if a.action == "login":
        runner.login()
        return 0
    if a.action == "revoke":
        state = runner.load_state()
        for s in ([a.site] if a.site else list(state)):
            state.pop(s, None)
        runner.save_state(state)
        print(f"automatic mode off for: {a.site or 'all sites'}")
        return 0
    if a.action == "status":
        state = runner.load_state()
        for name in runner.SITES:
            print(f"  {name:10} {'AUTO since ' + state[name]['approved_on'] if runner.auto_approved(state, name) else 'review (sample first)'}")
        return 0
    if a.action == "shortlist":
        # Recommended jobs always run in review mode: nothing is submitted without your confirmation,
        # even on a site where automatic mode is on.
        queue = runner.shortlist_queue(a.pick)
        for q in queue:
            print(f"  #{q.pick} {q.role} | {q.company} | {'assist (you submit)' if q.site is None else q.site.name}"
                  f"{' | SKIP: ' + q.skip if q.skip else ''}")
        runner.run(queue, force_review=True)
        return 0
    queue = runner.build_queue(a.site)
    if a.job:
        queue = [q for q in queue if canonical(q.url) == canonical(a.job)] or [
            runner.make_item(a.job, a.company or "", a.role or "")]
    if a.action == "queue":
        for i, q in enumerate(queue, 1):
            status = f"SKIP: {q.skip}" if q.skip else "ready"
            print(f"{i:3}. [{q.site.name if q.site else '-':9}] {q.role} | {q.company} | {q.verdict or '-'} | {status}")
        print(f"\nready: {sum(1 for q in queue if not q.skip)} of {len(queue)}")
        return 0
    if a.action == "prep":
        # prep is read-only, so a named job is inspected even before its CV is tailored
        targets = [q for q in queue if q.site] if a.job else [q for q in queue if not q.skip]
        for q in targets:
            runner.prep(q)
        return 0
    if a.action == "run":
        runner.run(queue)
        return 0
    return 1


def cmd_shortlist(a) -> int:
    from . import shortlist
    cfg = load(a.config)
    if a.gmail_in:
        print(f"stored {shortlist.merge_gmail(a.gmail_in)} Gmail check(s) in {shortlist.GMAIL}")
    if a.candidates:
        cands, dupes = shortlist.eligible(cfg)
        cands.sort(key=lambda c: c["match"], reverse=True)
        todo = [{k: c[k] for k in ("key", "title", "company", "location", "match", "official_url",
                                   "research_needed", "gmail_checked")} for c in cands]
        print(json.dumps({"candidates": todo, "duplicates": [
            {"title": d["title"], "company": d["company"], "why": d["duplicate"]} for d in dupes]},
            indent=1, ensure_ascii=False))
        return 0
    result = shortlist.build(cfg)
    js, page = shortlist.write(result)
    print(f"top {len(result['top'])} of {len(result['top']) + len(result['below_cut'])} above match "
          f"{result['settings']['min_match']} | duplicates excluded {len(result['duplicates'])}")
    for c in result["top"]:
        q = c["company_quality"]
        print(f"  #{c['pick']} {c['final']:5} | match {c['match']} | company {q['quality'] if q['quality'] is not None else 'n/a':>3} "
              f"| {q['recommendation']:8} | {c['title']} | {c['company']} | {c['location'] or '?'}")
        for f in c["flags"]:
            print(f"      ! {f}")
    for d in result["duplicates"]:
        print(f"  duplicate: {d['title']} | {d['company']}: {d['duplicate']}")
    print(f"shortlist: {js}\npage: {page}")
    return 0


def cmd_resume(a) -> int:
    from . import resume
    from .config import ROOT
    if a.samples:
        data = resume.load(ROOT / "config" / "resume_sample.json")
        out = ROOT / "config" / "resume_samples"
        for fmt in resume.FORMATS:
            n = resume.render_pdf(data, fmt, out / f"sample_{fmt}.pdf", out / f"sample_{fmt}.png")
            print(f"{fmt:15} {n} page(s) -> {out / f'sample_{fmt}.pdf'}")
        return 0
    if not (a.data and a.out):
        print("give --data <resume.json> --out <file.pdf> (or --samples)")
        return 1
    fmt = a.format or "plain"
    n = resume.render_pdf(resume.load(a.data), fmt, a.out, a.png)
    lo, hi = resume.PAGES[fmt]
    print(f"{fmt}: {n} page(s) -> {a.out}" + ("" if lo <= n <= hi else f"  ! expected {lo}-{hi} pages"))
    return 0 if lo <= n <= hi else 1


def canonical(url: str) -> str:
    from .dedup import canonical_url
    return canonical_url(url)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jobradar", description=__doc__)
    p.add_argument("--config", help="search config (default profile/search.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="fetch watched ATS boards (+ LinkedIn), filter, de-dupe")
    s.add_argument("--linkedin", action="store_true", help="also run LinkedIn public job search (needs Bun)")
    s.add_argument("--no-boards", action="store_true", help="skip ATS boards")
    s.add_argument("--incremental", action="store_true",
                   help="only jobs posted since each source's last successful run (data/scan_state.json)")
    s.add_argument("--out"); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_scan)

    q = sub.add_parser("queries", help="print search queries for the agent to run")
    q.add_argument("kind", choices=["ats", "posts", "browser"])
    q.set_defaults(fn=cmd_queries)

    d = sub.add_parser("discover", help="search-result URLs -> new ATS boards")
    d.add_argument("--in", dest="input", required=True); d.add_argument("--scan", action="store_true")
    d.add_argument("--out"); d.add_argument("--dry-run", action="store_true")
    d.set_defaults(fn=cmd_discover)

    po = sub.add_parser("posts", help="ingest #hiring post results (websearch or browser)")
    po.add_argument("--in", dest="input", required=True)
    po.add_argument("--via", choices=["websearch", "browser"], default="websearch")
    po.add_argument("--dry-run", action="store_true")
    po.set_defaults(fn=cmd_posts)

    r = sub.add_parser("record", help="mark jobs from a JSON file as seen")
    r.add_argument("--in", dest="input", required=True); r.add_argument("--status", default="new")
    r.set_defaults(fn=cmd_record)

    o = sub.add_parser("outreach-page", help="build the one-click outreach HTML page")
    o.add_argument("--in", dest="input", required=True); o.add_argument("--out", required=True)
    o.add_argument("--strict", action="store_true")
    o.set_defaults(fn=cmd_outreach_page)

    ap = sub.add_parser("apply", help="Playwright auto-apply (review a sample per site, then automatic if you approve)")
    ap.add_argument("action", choices=["queue", "prep", "run", "login", "status", "revoke", "shortlist"])
    ap.add_argument("--pick", type=int, help="shortlist: the job number on the latest shortlist (default: all)")
    ap.add_argument("--site", choices=["greenhouse", "lever", "ashby", "workday", "linkedin"])
    ap.add_argument("--job", help="a single job URL")
    ap.add_argument("--company"); ap.add_argument("--role")
    ap.set_defaults(fn=cmd_apply)

    sl = sub.add_parser("shortlist", help="top jobs by match + company quality, minus ones already applied to")
    sl.add_argument("--candidates", action="store_true",
                    help="list jobs above the match bar that still need AmbitionBox research or a Gmail check")
    sl.add_argument("--gmail-in", help="JSON from the agent's Gmail search: [{key, status, evidence}]")
    sl.set_defaults(fn=cmd_shortlist)

    rs = sub.add_parser("resume", help="render a resume (plain | sidebar | sidebar_metric) from a JSON data file")
    rs.add_argument("--data"); rs.add_argument("--out"); rs.add_argument("--png")
    rs.add_argument("--format", choices=["plain", "sidebar", "sidebar_metric"])
    rs.add_argument("--samples", action="store_true", help="render the three formats with made-up sample data")
    rs.set_defaults(fn=cmd_resume)

    a = p.parse_args(argv)
    return a.fn(a)
