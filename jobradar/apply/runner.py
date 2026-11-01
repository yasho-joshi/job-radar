"""Apply runner: supervised sample per site, then automatic only after the user approves.

Flow per site (greenhouse, lever, ashby, linkedin):
  1. REVIEW mode: open the job in a visible browser, fill every field the user's answers cover,
     ask the user for anything missing, show what will be sent, and wait for "submit" in the terminal.
  2. After a successful reviewed submission the user chooses: automatic for the rest of this site's
     queue, one more manual run, or stop. Approval is stored per site and expires after 7 days.
  3. AUTO mode: same filling, no submit prompt. It still pauses for unknown questions and CAPTCHAs,
     never solves a CAPTCHA, and stops at login walls. Caps: 10 jobs a run (LinkedIn 5), with pauses.
Every submission saves a screenshot of the filled form and the answers used, and updates the tracker.
"""

from __future__ import annotations

import csv
import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import DATA, ROOT
from ..dedup import canonical_url
from .answers import AnswerBank, choose_for
from .fields import Field, discover, fill
from .sites import SITES, Site, blocked_reason, detect, page_says

STATE = DATA / "apply_state.json"
TRACKER = DATA / "tracker.csv"
BROWSER_PROFILE = DATA / "browser-profile"
TRACKER_HEADER = ["date", "company", "role", "source", "status", "fit", "notes", "cv_file", "cover_file", "job_url", "deadline"]
APPROVAL_DAYS = 7
MAX_PER_RUN = 10
FIT_OK = {"strong fit", "good fit"}


def slug(company: str, role: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", f"{company}_{role}".lower()))
    return re.sub(r"_+", "_", s).strip("_")


@dataclass
class QueueItem:
    company: str
    role: str
    url: str
    site: Site | None
    verdict: str = ""
    score: float | None = None
    location: str = ""
    files: dict = field(default_factory=dict)
    skip: str = ""

    @property
    def slug(self) -> str:
        return slug(self.company, self.role)


class Console:
    """Terminal I/O. Swappable in tests."""

    def say(self, msg: str = "") -> None:
        print(msg, flush=True)

    def ask(self, prompt: str) -> str:
        print("\a", end="")       # terminal bell so the user notices a pause
        return input(prompt).strip()


# ---------------------------------------------------------------- state and records
def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def auto_approved(state: dict, site: str) -> bool:
    s = state.get(site) or {}
    if not s.get("auto"):
        return False
    try:
        return date.fromisoformat(s["approved_on"]) >= date.today() - timedelta(days=APPROVAL_DAYS)
    except (KeyError, ValueError):
        return False


def applied_urls() -> set[str]:
    if not TRACKER.exists():
        return set()
    with open(TRACKER, encoding="utf-8", newline="") as fh:
        return {canonical_url(r.get("job_url", "")) for r in csv.DictReader(fh)
                if r.get("status") not in ("drafted", "") and r.get("job_url")}


def record_application(item: QueueItem, notes: str) -> None:
    new = not TRACKER.exists()
    TRACKER.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(TRACKER_HEADER)
        w.writerow([date.today().isoformat(), item.company, item.role, item.site.name if item.site else "",
                    "applied", item.score or "", notes.replace(",", ";"), item.files.get("resume", ""),
                    item.files.get("cover", ""), item.url, ""])
    seen = DATA / "seen.jsonl"
    if seen.exists():
        rows, key = [], canonical_url(item.url)
        for line in seen.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                rows.append(line)
                continue
            if r.get("url") == key:
                r["status"] = "applied"
            rows.append(json.dumps(r))
        seen.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- queue
def build_queue(only_site: str | None = None) -> list[QueueItem]:
    seen = DATA / "seen.jsonl"
    rows = [json.loads(l) for l in seen.read_text(encoding="utf-8").splitlines() if l.strip()] if seen.exists() else []
    done = applied_urls()
    out = []
    for r in rows:
        if r.get("status") not in ("ranked", "new"):
            continue
        item = QueueItem(company=r.get("company", ""), role=r.get("title", ""), url=r.get("url", ""),
                         site=detect(r.get("url", "")), verdict=r.get("rank_verdict", ""), score=r.get("rank_score"),
                         location=r.get("location") or "")
        cv = ROOT / "output" / "cv" / f"{item.slug}.pdf"
        cover = ROOT / "output" / "cover" / f"{item.slug}.pdf"
        if cv.exists():
            item.files["resume"] = str(cv)
        if cover.exists():
            item.files["cover"] = str(cover)
        if item.site is None:
            item.skip = "site not supported for auto-apply (apply manually)"
        elif only_site and item.site.name != only_site:
            continue
        elif canonical_url(item.url) in done:
            item.skip = "already applied"
        elif (item.verdict or "").lower() not in FIT_OK:
            item.skip = f"fit '{item.verdict or 'unranked'}' (only Strong/Good fit; run /rank)"
        elif "resume" not in item.files:
            item.skip = f"no tailored CV at output/cv/{item.slug}.pdf (run /tailor)"
        out.append(item)
    return out


def make_item(url: str, company: str, role: str) -> QueueItem:
    """A one-off job the user names explicitly. Same gates as the queue except the fit band."""
    item = QueueItem(company=company, role=role, url=url, site=detect(url), verdict="(named by you)")
    cv = ROOT / "output" / "cv" / f"{item.slug}.pdf"
    cover = ROOT / "output" / "cover" / f"{item.slug}.pdf"
    if cv.exists():
        item.files["resume"] = str(cv)
    if cover.exists():
        item.files["cover"] = str(cover)
    if item.site is None:
        item.skip = "site not supported for auto-apply (apply manually)"
    elif not company or not role:
        item.skip = "give --company and --role so the tailored CV can be found"
    elif canonical_url(url) in applied_urls():
        item.skip = "already applied"
    elif "resume" not in item.files:
        item.skip = f"no tailored CV at output/cv/{item.slug}.pdf (run /tailor)"
    return item


def job_answers(item: QueueItem) -> dict:
    p = DATA / "applications" / item.slug / "answers.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------------------------------------------------------------- filling
def fill_page(page, item: QueueItem, bank: AnswerBank, io: Console, root: str = "") -> tuple[list[dict], bool]:
    """Fill the visible form. Returns (log of every field, ok). ok=False means the user skipped."""
    answers = job_answers(item)
    log = []
    for f in discover(page, root or None):
        if f.kind != "file" and f.value and f.kind not in ("radio", "checkbox", "yesno"):
            log.append({"question": f.label, "answer": f.value, "source": "already filled"})
            continue
        ans = bank.resolve(f, answers, item.files, item.location)
        value = choose_for(f, ans)
        if value is None and (f.required or ans.source in ("consent needs your OK",)):
            value = ask_user(f, ans.source, io, bank)
            if value is None:
                return log, False
            ans.source = "you, during this run"
        if value is None or value == "":
            if f.required:
                return log, False
            continue
        try:
            ok = fill(page, f, value, root)
        except Exception as e:
            io.say(f"   could not fill '{f.label}': {str(e).splitlines()[0][:160]}")
            if f.required:
                return log, False
            continue
        if not ok and f.required:
            io.say(f"   the answer '{value}' does not fit the options for '{f.label}': {f.options}")
            value = ask_user(f, "answer did not match the options", io, bank)
            if value is None or not fill(page, f, value, root):
                return log, False
        shown = Path(value).name if f.kind == "file" else value
        log.append({"question": f.label, "answer": shown, "source": ans.source, "required": f.required})
    return log, True


def ask_user(f: Field, why: str, io: Console, bank: AnswerBank) -> str | None:
    io.say(f"\n   Needs your answer ({why}): {f.label or f.name}")
    if f.options:
        for i, o in enumerate(f.options, 1):
            io.say(f"     {i}. {o}")
    v = io.ask("   Your answer (number or text; Enter = skip this job): ")
    if not v:
        return None
    if f.options and v.isdigit() and 1 <= int(v) <= len(f.options):
        v = f.options[int(v) - 1]
    if io.ask("   Reuse this answer for the same question on future jobs? [Y/n] ").lower() != "n":
        bank.remember(f.label or f.name, v)
    return v


def click_button(page, pattern: str, root: str = "") -> bool:
    scope = page.locator(root) if root else page
    btn = scope.get_by_role("button", name=re.compile(pattern, re.I))
    if btn.count() == 0:
        btn = scope.locator("input[type=submit]").filter(has_text=re.compile(pattern, re.I))
    if btn.count() == 0:
        return False
    btn.first.click()
    return True


def wait_for_user_on_block(page, io: Console, reason: str) -> bool:
    io.say(f"\n   Stopped: {reason}. job-radar never solves CAPTCHAs or logs in for you.")
    v = io.ask("   Handle it in the browser window, then press Enter to continue (or type 'skip'): ")
    return v.lower() != "skip" and blocked_reason(page) is None


# ---------------------------------------------------------------- one job
def apply_one(page, item: QueueItem, bank: AnswerBank, io: Console, review: bool) -> str:
    """Returns 'submitted', 'skipped', 'quit', or 'failed: ...'."""
    site = item.site
    out_dir = DATA / "applications" / item.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    page.goto(site.apply_url(item.url), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    reason = blocked_reason(page)
    if reason and not wait_for_user_on_block(page, io, reason):
        return f"failed: {reason}"
    if page_says(page, site.closed_re):
        return "failed: posting is closed"

    log: list[dict] = []
    if site.name == "linkedin":
        if not click_button(page, r"^easy apply"):
            return "failed: no Easy Apply button (external application; apply on the company site)"
        page.wait_for_timeout(1500)
        for _ in range(12):                                    # Easy Apply is a multi-step dialog
            step_log, ok = fill_page(page, item, bank, io, site.root)
            log += step_log
            if not ok:
                return "skipped"
            if page.locator(site.root).get_by_role("button", name=re.compile(site.submit_re, re.I)).count():
                break
            if not click_button(page, site.next_re, site.root):
                return "failed: could not find the next step in Easy Apply"
            page.wait_for_timeout(1200)
            reason = blocked_reason(page)
            if reason and not wait_for_user_on_block(page, io, reason):
                return f"failed: {reason}"
        else:
            return "failed: Easy Apply had too many steps"
    else:
        log, ok = fill_page(page, item, bank, io)
        if not ok:
            return "skipped"

    shot = out_dir / "form_before_submit.png"
    page.screenshot(path=str(shot), full_page=True)
    (out_dir / "answers_used.json").write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")

    if review:
        io.say(f"\n   About to submit {item.role} at {item.company}. Fields:")
        for row in log:
            io.say(f"     - {row['question'][:70]}: {str(row['answer'])[:60]}   [{row['source']}]")
        io.say(f"   Screenshot: {shot}")
        while True:
            v = io.ask("   [s] submit  [e] I'll edit in the browser first  [k] skip  [q] quit: ").lower()
            if v == "e":
                io.ask("   Edit in the browser window, then press Enter here: ")
                page.screenshot(path=str(shot), full_page=True)
                continue
            if v in ("k", "q"):
                return "skipped" if v == "k" else "quit"
            if v == "s":
                break

    reason = blocked_reason(page)
    if reason and not wait_for_user_on_block(page, io, reason):
        return f"failed: {reason}"
    if not click_button(page, site.submit_re, site.root):
        return "failed: submit button not found"
    page.wait_for_timeout(4000)
    reason = blocked_reason(page)                      # invisible CAPTCHAs can turn into challenges on submit
    if reason:
        if not wait_for_user_on_block(page, io, reason):
            return f"failed: {reason}"
        page.wait_for_timeout(3000)
    if page_says(page, site.success_re):
        (out_dir / "result.json").write_text(json.dumps({"submitted": datetime.now().isoformat(timespec="seconds"),
                                                         "mode": "review" if review else "auto", "url": item.url}),
                                             encoding="utf-8")
        record_application(item, f"auto-apply {'review' if review else 'auto'} {date.today().isoformat()}")
        return "submitted"
    page.screenshot(path=str(out_dir / "after_submit.png"), full_page=True)
    return "failed: no confirmation message after submit (check after_submit.png and the form for errors)"


# ---------------------------------------------------------------- the run
def run(queue: list[QueueItem], io: Console | None = None, headless: bool = False, page_factory=None,
        delay_scale: float = 1.0) -> dict:
    io = io or Console()
    bank = AnswerBank()
    state = load_state()
    todo = [q for q in queue if not q.skip]
    counts = {"submitted": 0, "skipped": 0, "failed": 0}
    per_site: dict[str, int] = {}
    if not todo:
        io.say("Nothing to apply to. Run `apply queue` to see why jobs are skipped.")
        return counts

    def _run(page):
        for item in todo:
            site = item.site
            if sum(per_site.values()) >= MAX_PER_RUN:
                io.say(f"Run limit of {MAX_PER_RUN} submissions reached; the rest wait for the next run.")
                break
            if per_site.get(site.name, 0) >= site.max_per_run:
                continue                                   # this site's cap is reached; others may continue
            review = not auto_approved(state, site.name)
            io.say(f"\n== {item.role} | {item.company} | {site.name} | {'REVIEW' if review else 'AUTO'}")
            try:
                result = apply_one(page, item, bank, io, review)
            except Exception as e:
                result = f"failed: {type(e).__name__}: {str(e)[:150]}"
            io.say(f"   -> {result}")
            if result == "quit":
                break
            key = "submitted" if result == "submitted" else "skipped" if result == "skipped" else "failed"
            counts[key] += 1
            if result == "submitted":
                per_site[site.name] = per_site.get(site.name, 0) + 1
                if review:
                    left = sum(1 for q in todo if q.site.name == site.name) - per_site[site.name]
                    choice = io.ask(f"\n   Sample for {site.name} went through. Apply to the remaining {left} "
                                    f"{site.name} job(s) automatically? [a] automatic  [m] one more manual  [q] stop: ").lower()
                    if choice == "a":
                        state[site.name] = {"auto": True, "approved_on": date.today().isoformat()}
                        save_state(state)
                        io.say(f"   Automatic mode on for {site.name} for {APPROVAL_DAYS} days. `apply revoke` turns it off.")
                    elif choice == "q":
                        break
            lo, hi = site.delay
            time.sleep(random.uniform(lo, hi) * delay_scale)

    if page_factory:                                   # tests inject a page
        _run(page_factory())
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=headless,
                                                       viewport={"width": 1280, "height": 900})
            try:
                _run(ctx.pages[0] if ctx.pages else ctx.new_page())
            finally:
                ctx.close()
    io.say(f"\nDone: {counts['submitted']} submitted, {counts['skipped']} skipped, {counts['failed']} failed.")
    return counts


def login(io: Console | None = None) -> None:
    """Open the persistent browser so the user can sign in to LinkedIn themselves."""
    io = io or Console()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.linkedin.com/login")
        io.ask("Sign in to LinkedIn in the browser window yourself, then press Enter here to save the session: ")
        ctx.close()
    io.say(f"Session saved in {BROWSER_PROFILE} (gitignored). job-radar never sees your password.")


def prep(item: QueueItem, io: Console | None = None) -> Path:
    """Read-only: open the form, list its questions and what the answer bank would put in each."""
    io = io or Console()
    bank = AnswerBank()
    from playwright.sync_api import sync_playwright
    out = DATA / "applications" / item.slug / "questions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=item.site.name != "linkedin")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(item.site.apply_url(item.url), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        root = None
        if item.site.name == "linkedin" and click_button(page, r"^easy apply"):
            page.wait_for_timeout(1500)
            root = item.site.root
        rows = []
        for f in discover(page, root):
            ans = bank.resolve(f, job_answers(item), item.files, item.location)
            rows.append({"question": f.label, "kind": f.kind, "required": f.required, "options": f.options,
                         "answer": choose_for(f, ans), "source": ans.source})
        ctx.close()
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    io.say(f"{len(rows)} questions; {sum(1 for r in rows if r['answer'] is None and r['required'])} required "
           f"without an answer -> {out}")
    return out
