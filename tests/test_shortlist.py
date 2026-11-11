"""Tests for the 3-day window, incremental scans, company quality, the shortlist and assisted apply.

Offline. The assisted-apply test needs Playwright + Chromium and is skipped otherwise.
Run: py -m unittest tests.test_shortlist
"""

import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobradar import cli, company, filters, shortlist, state  # noqa: E402
from jobradar.apply import answers as answers_mod  # noqa: E402
from jobradar.apply import runner  # noqa: E402
from jobradar.dedup import job_key  # noqa: E402
from jobradar.models import Job  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

TODAY = date(2026, 11, 10)
FORMS = ROOT / "tests" / "fixtures" / "forms"


class Window(unittest.TestCase):
    def test_linkedin_window_follows_last_success(self):
        now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        self.assertIsNone(state.window_minutes(None, 3, now))
        self.assertEqual(state.window_minutes(now - timedelta(minutes=30), 3, now), 90)    # 30 min + 1 h overlap
        self.assertEqual(state.window_minutes(now - timedelta(days=10), 3, now), 3 * 1440)  # never past 3 days

    def test_ats_postings_before_last_success_day_are_dropped(self):
        since = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
        self.assertTrue(state.posted_since("2026-11-09", since))
        self.assertFalse(state.posted_since("2026-11-08", since))
        self.assertTrue(state.posted_since(None, since))           # undated: decided by require_posted_date

    def test_three_days_and_undated_jobs(self):
        j = Job("Senior Product Manager", "Acme", "https://x.test/1", "greenhouse", "Bengaluru")
        self.assertTrue(filters.fresh_enough(j, 3))                     # undated kept by default
        self.assertFalse(filters.fresh_enough(j, 3, require_date=True))
        j.posted = (TODAY - timedelta(days=3)).isoformat()
        self.assertTrue(filters.fresh_enough(j, 3, TODAY, require_date=True))
        j.posted = (TODAY - timedelta(days=4)).isoformat()
        self.assertFalse(filters.fresh_enough(j, 3, TODAY, require_date=True))


class IncrementalScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        today = date.today().isoformat()
        self.cfg = {"search": {"roles": ["Senior Product Manager"], "locations": ["Bengaluru"], "remote_ok": True,
                               "max_age_days": 3, "ats_max_age_days": 3, "require_posted_date": True},
                    "linkedin": {}, "feeds": {}, "_path": "test",
                    "boards": [{"source": "greenhouse", "slug": "good"}, {"source": "greenhouse", "slug": "bad"}]}
        self.batch = [Job("Senior Product Manager", "Good", "https://boards.greenhouse.io/good/jobs/1", "greenhouse",
                          "Bengaluru", posted=today),
                      Job("Senior Product Manager, Payments", "Good", "https://boards.greenhouse.io/good/jobs/2",
                          "greenhouse", "Bengaluru", posted=None)]

        def fetch(board):
            if board["slug"] == "bad":
                raise RuntimeError("HTTP 503")
            return list(self.batch)
        self.fake = types.SimpleNamespace(fetch=fetch)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self):
        args = types.SimpleNamespace(config=None, incremental=True, no_boards=False, linkedin=False, out=None,
                                     dry_run=False)
        with mock.patch.object(cli, "DATA", self.data), mock.patch.object(cli, "load", return_value=self.cfg), \
                mock.patch.dict(cli.REGISTRY, {"greenhouse": self.fake}), mock.patch("builtins.print"):
            cli.cmd_scan(args)

    def test_failed_board_keeps_old_mark_and_seen_jobs_are_not_reprocessed(self):
        self.scan()
        st = json.loads((self.data / "scan_state.json").read_text(encoding="utf-8"))
        self.assertIn("greenhouse:good", st["sources"])
        self.assertNotIn("greenhouse:bad", st["sources"])        # retried in full next hour
        seen = (self.data / "seen.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(seen), 1)                            # the undated job is dropped
        runs = list((self.data / "runs").glob("*-scan.json"))
        self.assertEqual(len(runs), 1)
        self.scan()                                               # next hour, same postings
        self.assertEqual(len((self.data / "seen.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(len(list((self.data / "runs").glob("*-scan.json"))), 1)   # nothing new: no run file


def research(rating=4.0, reviews=(), cats=None, risks=(), salary=None, status="ok", fetched=TODAY):
    ab = {"fetched_date": fetched.isoformat(), "status": status, "overall_rating": rating,
          "category_ratings": cats or {}, "recent_reviews": list(reviews),
          "summary": {"sentiment": "Mixed", "risks": list(risks)}}
    if salary:
        ab["salary"] = salary
    return {"ambitionbox": ab}


def rev(days_ago, rating):
    return {"date": (TODAY - timedelta(days=days_ago)).isoformat(), "rating": rating}


class CompanyQuality(unittest.TestCase):
    def test_only_last_30_days_count(self):
        r = research(4.0, [rev(1, 5), rev(10, 5), rev(29, 5), rev(31, 1), {"date": "", "rating": 1}])
        a = company.assess(r, TODAY)
        self.assertEqual(a["recent_review_count"], 3)
        self.assertEqual(a["recent_avg"], 5.0)

    def test_good_company_is_apply(self):
        a = company.assess(research(4.2, [rev(2, 4), rev(5, 5), rev(9, 4)], {"salary": 4.0, "culture": 4.1}), TODAY)
        self.assertGreaterEqual(a["quality"], 70)
        self.assertEqual(a["recommendation"], "Apply")

    def test_two_high_risks_is_avoid(self):
        risks = [{"text": "layoffs", "severity": "high"}, {"text": "salary delays", "severity": "high"}]
        a = company.assess(research(4.2, [rev(2, 4), rev(5, 4), rev(9, 4)], risks=risks), TODAY)
        self.assertEqual(a["recommendation"], "Avoid")

    def test_poor_recent_reviews_is_avoid(self):
        a = company.assess(research(3.5, [rev(1, 1), rev(3, 2), rev(6, 1)]), TODAY)
        self.assertLess(a["quality"], 50)
        self.assertEqual(a["recommendation"], "Avoid")

    def test_salary_below_floor_downgrades_apply(self):
        sal = {"min_lpa": 20, "avg_lpa": 30, "max_lpa": 40}
        a = company.assess(research(4.4, [rev(2, 5), rev(4, 5), rev(8, 4)], salary=sal), TODAY, floor_lpa=55)
        self.assertEqual(a["recommendation"], "Consider")
        self.assertTrue(a["salary"].startswith("below floor"))

    def test_no_data_is_consider_without_score(self):
        a = company.assess(research(status="blocked"), TODAY)
        self.assertIsNone(a["quality"])
        self.assertEqual(a["recommendation"], "Consider")

    def test_research_cache_age(self):
        old = research(fetched=TODAY - timedelta(days=8))
        self.assertEqual(company.research_age_days(old, TODAY), 8)


class Shortlist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [mock.patch.object(shortlist, "DATA", d), mock.patch.object(shortlist, "ROOT", d),
                        mock.patch.object(shortlist, "GMAIL", d / "gmail_checks.json"),
                        mock.patch.object(shortlist, "TRACKER", d / "tracker.csv"),
                        mock.patch.object(company, "RESEARCH", d / "company_research")]
        for p in self.patches:
            p.start()
        self.d = d
        rows = [("Senior Product Manager", "Alpha", 90), ("Product Owner", "Beta", 85),
                ("Senior PM <script>x</script>", "Gamma", 95), ("Product Manager", "Delta", 80),
                ("Technical Product Manager", "Epsilon", 88), ("Platform Product Manager", "Zeta", 83),
                ("AI Product Manager", "Eta", 82), ("Product Manager, Payments", "Theta", 86)]
        with open(d / "seen.jsonl", "w", encoding="utf-8") as fh:
            for title, co, score in rows:
                fh.write(json.dumps({"key": job_key(co, title), "url": f"https://jobs.lever.co/{co.lower()}/1",
                                     "title": title, "company": co, "status": "ranked", "score": score,
                                     "verdict": "Strong"}) + "\n")
        (d / "tracker.csv").write_text("date,company,role,source,status,fit,notes,cv_file,cover_file,job_url,deadline\n"
                                       "2026-11-01,Beta,Product Owner,lever,applied,,,,,,\n", encoding="utf-8")
        (d / "company_research").mkdir()
        (d / "company_research" / "theta.json").write_text(json.dumps(research(
            2.5, [rev(1, 1), rev(2, 1), rev(3, 2)])), encoding="utf-8")
        (d / "company_research" / "alpha.json").write_text(json.dumps(research(
            4.5, [rev(1, 5), rev(2, 5), rev(3, 4)])), encoding="utf-8")
        self.cfg = {"shortlist": {"min_match": 80, "top_n": 5}}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_top5_above_80_without_duplicates(self):
        gm = self.d / "gm.json"
        gm.write_text(json.dumps([
            {"key": job_key("Epsilon", "Technical Product Manager"), "status": "applied_same_role",
             "evidence": "Thanks for applying, 2026-10-30"},
            {"key": job_key("Zeta", "Platform Product Manager"), "status": "applied_company", "evidence": "Re: PM role"},
            {"key": "x", "status": "sent an email"}]), encoding="utf-8")
        self.assertEqual(shortlist.merge_gmail(gm, TODAY), 2)    # an unknown status is ignored
        res = shortlist.build(self.cfg, TODAY)
        names = [c["company"] for c in res["top"]]
        self.assertNotIn("Delta", names)                         # 80 is not above 80
        self.assertNotIn("Beta", names + [c["company"] for c in res["below_cut"]])     # tracker duplicate
        self.assertIn("Beta", [x["company"] for x in res["duplicates"]])
        self.assertIn("Epsilon", [x["company"] for x in res["duplicates"]])           # Gmail duplicate
        self.assertLessEqual(len(res["top"]), 5)
        self.assertEqual(names[0], "Alpha")                      # strong company lifts a 90 above a 95 with no data
        self.assertNotIn("Theta", names[:4])                     # Avoid sorts last
        zeta = next(c for c in res["top"] + res["below_cut"] if c["company"] == "Zeta")
        self.assertTrue(any("applied to Zeta before" in f for f in zeta["flags"]))
        page = shortlist.render_html(res)
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_candidates_report_what_is_missing(self):
        cands, _ = shortlist.eligible(self.cfg, TODAY)
        by = {c["company"]: c for c in cands}
        self.assertFalse(by["Alpha"]["research_needed"])
        self.assertTrue(by["Gamma"]["research_needed"])
        self.assertFalse(by["Gamma"]["gmail_checked"])


class RunnerQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (runner.DATA, runner.TRACKER, runner.ROOT)
        runner.DATA, runner.TRACKER, runner.ROOT = d / "data", d / "data" / "tracker.csv", d
        (d / "data").mkdir()
        (d / "output" / "cv").mkdir(parents=True)
        self.d = d

    def tearDown(self):
        runner.DATA, runner.TRACKER, runner.ROOT = self.saved
        self.tmp.cleanup()

    def test_rank_verdict_keys_are_read(self):
        (self.d / "data" / "seen.jsonl").write_text(json.dumps(
            {"url": "https://jobs.lever.co/acme/1", "title": "PM", "company": "Acme", "status": "ranked",
             "score": 70, "verdict": "Good"}) + "\n", encoding="utf-8")
        q = runner.build_queue()
        self.assertTrue(q[0].skip.startswith("no tailored CV"), q[0].skip)   # fit passed; only the CV is missing
        self.assertTrue(runner.fit_ok("Strong Fit") and runner.fit_ok("good") and not runner.fit_ok("Moderate"))

    def test_shortlist_queue_assist_and_cv_gate(self):
        (self.d / "output" / "cv" / "acme_senior_pm.pdf").write_bytes(b"%PDF")
        sl = self.d / "s.json"
        sl.write_text(json.dumps({"top": [
            {"pick": 1, "company": "Acme", "title": "Senior PM", "url": "https://www.linkedin.com/jobs/view/123",
             "official_url": "https://careers.acme.test/jobs/9"},
            {"pick": 2, "company": "Bolt", "title": "PM", "url": "https://jobs.lever.co/bolt/1"}]}), encoding="utf-8")
        q = runner.shortlist_queue(path=sl)
        self.assertEqual(q[0].url, "https://www.linkedin.com/jobs/view/123")  # supported listing beats unknown page
        self.assertFalse(q[0].assist)
        self.assertIn("run /tailor for #2", q[1].skip)
        q1 = runner.shortlist_queue(pick=1, path=sl)
        self.assertEqual([i.pick for i in q1], [1])


class Secrets(unittest.TestCase):
    def test_passwords_are_never_remembered(self):
        with tempfile.TemporaryDirectory() as t:
            bank = answers_mod.AnswerBank(Path(t) / "none.toml", Path(t) / "learned.json")
            bank.remember("Create a password*", "hunter2")
            bank.remember("Notice period", "60 days")
            saved = json.loads((Path(t) / "learned.json").read_text(encoding="utf-8"))
            self.assertNotIn("hunter2", json.dumps(saved))
            self.assertIn("60 days", saved.values())


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class AssistedApply(unittest.TestCase):
    def test_fills_form_leaves_password_and_submit_to_user(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "answers.toml").write_text('[identity]\nfirst_name = "Test"\nlast_name = "Person"\n'
                                            'email = "contact@example.com"\nphone = "+91 90000 00000"\n',
                                            encoding="utf-8")
            (t / "preferences.toml").write_text('apply_email = "account@example.com"\n', encoding="utf-8")
            cv = t / "cv.pdf"
            cv.write_bytes(b"%PDF-1.4 test")
            saved = (runner.DATA, runner.TRACKER, runner.PREFERENCES, runner.AnswerBank.__init__.__defaults__)
            runner.DATA, runner.TRACKER, runner.PREFERENCES = t / "data", t / "data" / "tracker.csv", t / "preferences.toml"
            runner.AnswerBank.__init__.__defaults__ = (t / "answers.toml", t / "learned.json")
            item = runner.QueueItem(company="Testco", role="Senior Product Manager",
                                    url=(FORMS / "careers.html").as_uri(), site=None, assist=True,
                                    files={"resume": str(cv)})
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                replies = [lambda: page.evaluate("openApply()"),     # the user clicks Apply
                           lambda: page.evaluate("finishSignIn()"),  # the user types the password and signs in
                           "d"]                                      # the user reviewed and submitted

                class IO:
                    said = []

                    def say(self, m=""):
                        self.said.append(m)

                    def ask(self, prompt):
                        r = replies.pop(0)
                        if callable(r):
                            r()
                            return ""
                        return r
                io = IO()
                try:
                    counts = runner.run([item], io=io, page_factory=lambda: page, delay_scale=0, force_review=True)
                    acct, pw = page.input_value("#acct"), page.input_value("#pw")
                    fn, em = page.input_value("#fn"), page.input_value("#em")
                    submitted = page.evaluate("window.submitted")
                finally:
                    browser.close()
                    (runner.DATA, runner.TRACKER, runner.PREFERENCES,
                     runner.AnswerBank.__init__.__defaults__) = saved
            self.assertEqual(counts["submitted"], 1, io.said)
            self.assertEqual(acct, "account@example.com")        # account email prefilled on sign-in
            self.assertEqual(pw, "")                              # password never touched
            self.assertEqual((fn, em), ("Test", "contact@example.com"))
            self.assertFalse(submitted)                           # job-radar never clicks submit here
            self.assertIn("applied", (t / "data" / "tracker.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
