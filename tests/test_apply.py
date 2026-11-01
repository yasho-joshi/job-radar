"""End-to-end apply tests against local fixture forms (no real sites, no real submissions).

Needs Playwright + Chromium; skipped otherwise. Run: py -m unittest tests.test_apply
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

from jobradar.apply import answers as answers_mod  # noqa: E402
from jobradar.apply import runner  # noqa: E402
from jobradar.apply.fields import Field, pick_option  # noqa: E402
from jobradar.apply.sites import SITES, blocked_reason, detect  # noqa: E402

FORMS = ROOT / "tests" / "fixtures" / "forms"

ANSWERS_TOML = """
[identity]
first_name = "Test"
last_name = "Person"
full_name = "Test Person"
email = "test@example.com"
phone = "+91 90000 00000"
current_company = "Example Corp"
linkedin = "https://www.linkedin.com/in/test-person"
[work_rights]
authorized_countries = ["India"]
[standard]
expected_salary = "INR 55 LPA"
willing_to_relocate = "No"
[eeo]
policy = "decline"
"""


class ScriptedConsole:
    def __init__(self, replies):
        self.replies = list(replies)
        self.asked, self.said = [], []

    def say(self, msg=""):
        self.said.append(msg)

    def ask(self, prompt):
        self.asked.append(prompt)
        if not self.replies:
            raise AssertionError(f"unexpected prompt: {prompt}")
        r = self.replies.pop(0)
        if callable(r):          # a step the "user" performs in the browser (e.g. signing in)
            r()
            return ""
        return r


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class ApplyFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "profile").mkdir()
        (t / "profile" / "answers.toml").write_text(ANSWERS_TOML, encoding="utf-8")
        self._saved = (runner.DATA, runner.STATE, runner.TRACKER, answers_mod.ANSWERS, answers_mod.LEARNED,
                       runner.AnswerBank.__init__.__defaults__)
        runner.DATA, runner.STATE, runner.TRACKER = t / "data", t / "data" / "apply_state.json", t / "data" / "tracker.csv"
        runner.AnswerBank.__init__.__defaults__ = (t / "profile" / "answers.toml", t / "profile" / "answers_learned.json")
        self.cv = t / "cv.pdf"
        self.cv.write_bytes(b"%PDF-1.4 test")
        self.t = t

    def tearDown(self):
        (runner.DATA, runner.STATE, runner.TRACKER, answers_mod.ANSWERS, answers_mod.LEARNED,
         runner.AnswerBank.__init__.__defaults__) = self._saved
        self.tmp.cleanup()

    def item(self, fixture, site_name, role="Senior Product Manager", job_answers=None):
        site = SITES[site_name] if site_name in ("greenhouse", "linkedin") else dataclasses.replace(
            SITES[site_name], name=f"{site_name}-fixture")
        it = runner.QueueItem(company="Testco", role=role, url=(FORMS / fixture).as_uri(), site=site,
                              verdict="Strong Fit", files={"resume": str(self.cv)})
        if job_answers:
            d = runner.DATA / "applications" / it.slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "answers.json").write_text(json.dumps(job_answers), encoding="utf-8")
        return it

    def run_items(self, items, io):
        page = self.browser.new_page()
        try:
            counts = runner.run(items, io=io, page_factory=lambda: page, delay_scale=0)
            payload = json.loads(page.inner_text("#payload")) if page.locator("#payload").count() else {}
        finally:
            page.close()
        return counts, payload

    def test_greenhouse_review_sample_then_stop(self):
        it = self.item("greenhouse.html", "greenhouse",
                       job_answers={"Why do you want to work at Testco?*": "Your payments roadmap matches my checkout work."})
        io = ScriptedConsole(["s", "q"])          # submit the sample, then stop instead of going automatic
        counts, payload = self.run_items([it], io)
        self.assertEqual(counts["submitted"], 1, io.said)
        self.assertEqual(payload["first_name"], "Test")
        self.assertEqual(payload["question_1"], "Yes")          # combobox: authorized in India
        self.assertEqual(payload["question_2"], "Yes")          # sponsorship needed for the US
        self.assertEqual(payload["question_3"], "INR 55 LPA")
        self.assertEqual(payload["gender"], "Decline")          # demographic: decline by policy
        self.assertEqual(payload["resume"], "cv.pdf")
        self.assertTrue((runner.DATA / "applications" / it.slug / "form_before_submit.png").exists())
        self.assertIn("applied", runner.TRACKER.read_text(encoding="utf-8"))
        self.assertFalse(runner.auto_approved(runner.load_state(), "greenhouse"))

    def test_lever_asks_unknown_then_user_approves_auto(self):
        it = self.item("lever.html", "lever",
                       job_answers={"Tell us about a key metric you owned": "Card issuance grew 70% YoY."})
        io = ScriptedConsole(["60 days", "y", "s", "a"])   # answer notice period, reuse it, submit, go automatic
        counts, payload = self.run_items([it], io)
        self.assertEqual(counts["submitted"], 1, io.said)
        self.assertEqual(payload["cards[abc][field0]"], "60 days")
        self.assertEqual(payload["urls[LinkedIn]"], "https://www.linkedin.com/in/test-person")
        learned = json.loads((self.t / "profile" / "answers_learned.json").read_text(encoding="utf-8"))
        self.assertEqual(learned["what is your notice period"], "60 days")
        self.assertTrue(runner.auto_approved(runner.load_state(), "lever-fixture"))

    def test_ashby_auto_mode_runs_without_prompts(self):
        runner.save_state({"ashby-fixture": {"auto": True, "approved_on": runner.date.today().isoformat()}})
        it = self.item("ashby.html", "ashby")
        io = ScriptedConsole([])                          # any prompt fails the test
        counts, payload = self.run_items([it], io)
        self.assertEqual(counts["submitted"], 1, io.said)
        self.assertEqual(payload["relocate"], "No")       # Yes/No buttons
        self.assertEqual(payload["race"], "Decline")

    def test_linkedin_easy_apply_multistep(self):
        it = self.item("linkedin.html", "linkedin")
        io = ScriptedConsole(["Yes", "n", "s", "q"])      # hybrid question, don't reuse, submit, stop
        counts, payload = self.run_items([it], io)
        self.assertEqual(counts["submitted"], 1, io.said)
        self.assertEqual(payload["phone"], "+91 90000 00000")
        self.assertEqual(payload["hybrid"], "Yes")
        self.assertEqual(payload["resume"], "cv.pdf")

    def test_user_skip_and_missing_answer_never_submit(self):
        it = self.item("lever.html", "lever")             # no job answers for the essay question
        io = ScriptedConsole(["60 days", "n", ""])        # notice period, then Enter = skip on the essay
        counts, _ = self.run_items([it], io)
        self.assertEqual(counts["submitted"], 0)
        self.assertEqual(counts["skipped"], 1)
        self.assertFalse(runner.TRACKER.exists())

    def test_workday_signin_handoff_steps_and_review(self):
        (self.t / "profile" / "answers.toml").write_text(ANSWERS_TOML.replace(
            "[work_rights]", 'country = "India"\n[work_rights]').replace(
            'expected_salary = "INR 55 LPA"',
            'expected_salary = "INR 50 LPA"\nnotice_period = "30 days"\nhear_about = "LinkedIn"'),
            encoding="utf-8")
        it = runner.QueueItem(company="Testco", role="Senior Product Manager",
                              url=(FORMS / "workday.html").as_uri() + "?signin=1", site=SITES["workday"],
                              verdict="Strong Fit", files={"resume": str(self.cv)})
        page = self.browser.new_page()
        io = ScriptedConsole([lambda: page.evaluate("finishSignIn()"),   # the user signs in themselves
                              "1", "n",                                   # consent checkbox: user says yes, don't reuse
                              "s", "q"])                                  # submit the sample, then stop
        try:
            counts = runner.run([it], io=io, page_factory=lambda: page, delay_scale=0)
            payload = json.loads(page.inner_text("#payload")) if page.locator("#payload").count() else {}
        finally:
            page.close()
        self.assertEqual(counts["submitted"], 1, io.said)
        self.assertTrue(any("sign in" in s.lower() for s in io.said))
        self.assertEqual(payload["fn"], "Test")
        self.assertEqual(payload["ctry"], "India")                # Select One dropdown
        self.assertEqual(payload["src"], "LinkedIn")              # selectinput picker
        self.assertEqual(payload["auth"], "Yes")
        self.assertEqual(payload["sp"], "No")                     # India: no sponsorship needed
        self.assertEqual(payload["np"], "30 days")
        self.assertEqual(payload["ctc"], "INR 50 LPA")
        self.assertEqual(payload["gen"], "I do not wish to self-identify")
        self.assertEqual(payload["resume"], "cv.pdf")

    def test_captcha_challenge_is_detected(self):
        page = self.browser.new_page()
        page.set_content('<iframe src="about:blank#recaptcha/api2/bframe" title="recaptcha challenge" '
                         'style="width:400px;height:500px"></iframe>')
        self.assertEqual(blocked_reason(page), "CAPTCHA challenge")
        page.close()


class Rules(unittest.TestCase):
    def test_site_detection(self):
        self.assertEqual(detect("https://job-boards.greenhouse.io/acme/jobs/1").name, "greenhouse")
        self.assertEqual(detect("https://jobs.lever.co/acme/1").name, "lever")
        self.assertEqual(detect("https://www.linkedin.com/jobs/view/123").name, "linkedin")
        self.assertEqual(detect("https://acme.wd5.myworkdayjobs.com/x/job/1").name, "workday")
        self.assertIsNone(detect("https://evil-lever.co/acme/1"))
        self.assertEqual(SITES["lever"].apply_url("https://jobs.lever.co/a/1"), "https://jobs.lever.co/a/1/apply")

    def test_pick_option_never_guesses(self):
        self.assertEqual(pick_option(["Yes, I am authorized", "No"], "Yes"), 0)
        self.assertIsNone(pick_option(["Option A", "Option B"], "Yes"))
        self.assertIsNone(pick_option(["0-2 years", "2-5 years"], "14"))

    def test_work_rights_per_country(self):
        bank = answers_mod.AnswerBank.__new__(answers_mod.AnswerBank)
        bank.cfg = {"work_rights": {"authorized_countries": ["India"]}}
        bank.learned = {}
        f = lambda label: Field(jr="0", kind="text", label=label)
        self.assertEqual(bank.resolve(f("Are you legally authorized to work in India?"), {}, {}).value, "Yes")
        self.assertEqual(bank.resolve(f("Are you authorized to work in the United States?"), {}, {}).value, "No")
        self.assertEqual(bank.resolve(f("Will you require visa sponsorship to work in Germany?"), {}, {}).value, "Yes")
        self.assertIsNone(bank.resolve(f("Do you require sponsorship?"), {}, {}).value)      # no country: ask


if __name__ == "__main__":
    unittest.main()
