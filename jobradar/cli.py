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


def _jobs_out(jobs: list[Job], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([j.to_dict() for j in jobs], indent=1, ensure_ascii=False), encoding="utf-8")


def _summary(jobs: list[Job]) -> None:
    for j in jobs:
        print(f"  [{j.source:10}] {j.title} | {j.company} | {j.location or '?'} | {j.work_mode or '?'} | {j.posted or 'date ?'}")


def fetch_boards(boards: list[dict], cfg: dict) -> tuple[list[Job], list[str]]:
    jobs, errors = [], []
    roles = cfg["search"].get("roles", [])
    for b in boards:
        mod = REGISTRY.get(b.get("source"))
        if not mod:
            errors.append(f"unknown source in board: {b}")
            continue
        try:
            if b["source"] == "workday":
                # Workday's search box is a plain keyword search, so run one search per role.
                for role in roles or [""]:
                    jobs += mod.fetch(b, role)
            else:
                jobs += mod.fetch(b)   # these APIs return the whole board; filters do the matching
        except Exception as e:
            errors.append(f"{b.get('source')} {b.get('slug') or b.get('careers_url')}: {e}")
    return jobs, errors


def cmd_scan(a) -> int:
    cfg = load(a.config)
    all_jobs, errors = [], []
    if not a.no_boards:
        got, err = fetch_boards(cfg["boards"], cfg)
        all_jobs += got
        errors += err
    if a.linkedin:
        got, err = linkedin.search_all(cfg)
        all_jobs += got
        errors += err
    titled = filters.by_title(all_jobs, cfg)
    errors += workday.fetch_details(titled)       # real locations for "2 Locations" rows
    matched = filters.apply(titled, cfg)
    store = SeenStore(DATA / "seen.jsonl")
    new, dupes = store.split(matched)
    out = Path(a.out or DATA / "runs" / f"{date.today().isoformat()}-scan.json")
    _jobs_out(new, out)
    if not a.dry_run:
        store.record(new)
    print(f"config: {cfg['_path']}")
    print(f"fetched {len(all_jobs)} | matched {len(matched)} | new {len(new)} | already seen {len(dupes)}")
    _summary(new)
    for e in errors:
        print(f"  ! {e}", file=sys.stderr)
    print(f"new jobs written to {out}")
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
    ap.add_argument("action", choices=["queue", "prep", "run", "login", "status", "revoke"])
    ap.add_argument("--site", choices=["greenhouse", "lever", "ashby", "linkedin"])
    ap.add_argument("--job", help="a single job URL")
    ap.add_argument("--company"); ap.add_argument("--role")
    ap.set_defaults(fn=cmd_apply)

    a = p.parse_args(argv)
    return a.fn(a)
