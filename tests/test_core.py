"""Offline tests. Run: py -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobradar import feeds, filters, outreach, queries  # noqa: E402
from jobradar.dedup import SeenStore, canonical_url, job_key, norm_title  # noqa: E402
from jobradar.models import Job, html_to_text  # noqa: E402
from jobradar.sources import ashby, greenhouse, lever, workday  # noqa: E402

CFG = {"search": {"roles": ["Product Owner", "Technical Product Manager", "Senior Product Manager"],
                  "exclude_titles": ["intern", "associate product manager"],
                  "locations": ["Bengaluru", "Bangalore"], "also_accept": ["Germany"],
                  "work_modes": ["remote", "hybrid", "onsite"], "remote_ok": True, "max_age_days": 14},
       "feeds": {"place_hashtags": ["#bengaluru"], "mode_hashtags": ["#remote", "#hybrid"]}}


def job(title="Senior Product Manager", location="Bengaluru, India", mode="", posted=None, source="greenhouse",
        company="Acme"):
    return Job(title=title, company=company, url=f"https://x.test/{title}", source=source, location=location,
               work_mode=mode, posted=posted)


class TitleFilter(unittest.TestCase):
    def test_matches_roles_and_abbreviations(self):
        roles = CFG["search"]["roles"]
        self.assertTrue(filters.title_matches("Sr. Product Manager, Payments", roles))
        self.assertTrue(filters.title_matches("Product Owner - Checkout", roles))
        self.assertTrue(filters.title_matches("Senior TPM", roles))
        self.assertTrue(filters.title_matches("Product Manager III", roles))   # 'senior' optional

    def test_rejects_lookalikes_and_excluded(self):
        roles, ex = CFG["search"]["roles"], CFG["search"]["exclude_titles"]
        self.assertFalse(filters.title_matches("Product Marketing Manager", roles))
        self.assertFalse(filters.title_matches("Associate Product Manager", roles, ex))
        self.assertFalse(filters.title_matches("Product Manager Intern", roles, ex))


class LocationFilter(unittest.TestCase):
    def test_place_and_also_accept(self):
        self.assertTrue(filters.location_matches(job(location="Bangalore, KA"), CFG["search"]))
        self.assertTrue(filters.location_matches(job(location="Berlin, Germany"), CFG["search"]))
        self.assertFalse(filters.location_matches(job(location="Pune, India"), CFG["search"]))

    def test_remote_rules(self):
        s = CFG["search"]
        self.assertTrue(filters.location_matches(job(location="Remote", mode="remote"), s))
        self.assertTrue(filters.location_matches(job(location="Remote - Worldwide"), s))
        self.assertFalse(filters.location_matches(job(location="US - Remote", mode="remote"), s))
        self.assertFalse(filters.location_matches(job(location="Remote, Canada"), s))

    def test_freshness_keeps_unknown_dates(self):
        today = date(2026, 11, 1)
        self.assertTrue(filters.fresh_enough(job(posted=None), 14, today))
        self.assertTrue(filters.fresh_enough(job(posted="2026-10-25"), 14, today))
        self.assertFalse(filters.fresh_enough(job(posted="2026-09-01"), 14, today))


class Dedup(unittest.TestCase):
    def test_canonical_linkedin_and_tracking(self):
        a = canonical_url("https://in.linkedin.com/jobs/view/sr-pm-at-acme-4459596196?trk=x&refId=y")
        b = canonical_url("https://www.linkedin.com/jobs/view/4459596196/")
        self.assertEqual(a, b)
        self.assertEqual(canonical_url("https://jobs.lever.co/acme/1?utm_source=li&lever-source=x"),
                         "https://jobs.lever.co/acme/1")

    def test_keys_keep_team_but_drop_noise(self):
        self.assertEqual(job_key("Acme Pvt Ltd", "Sr Product Manager"), job_key("ACME", "Senior Product Manager"))
        self.assertNotEqual(norm_title("Senior PM - Payments"), norm_title("Senior PM - Fraud"))
        self.assertEqual(norm_title("Product Owner (m/f/d)"), norm_title("Product Owner"))

    def test_store_prefers_ats_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            store = SeenStore(Path(d) / "seen.jsonl")
            li = job(source="linkedin")
            li.url = "https://www.linkedin.com/jobs/view/123456789"
            gh = job(source="greenhouse")
            new, dupes = store.split([li, gh])
            self.assertEqual([j.source for j in new], ["greenhouse"])
            self.assertEqual(len(dupes), 1)
            store.record(new)
            new2, _ = SeenStore(Path(d) / "seen.jsonl").split([job()])
            self.assertEqual(new2, [])


class Discovery(unittest.TestCase):
    def test_board_from_url(self):
        self.assertEqual(queries.board_from_url("https://job-boards.greenhouse.io/stripe/jobs/123"),
                         {"source": "greenhouse", "slug": "stripe"})
        self.assertEqual(queries.board_from_url("https://jobs.eu.lever.co/acme/abc"),
                         {"source": "lever", "slug": "acme", "region": "eu"})
        self.assertEqual(queries.board_from_url("https://jobs.ashbyhq.com/Notion/xyz"),
                         {"source": "ashby", "slug": "Notion"})
        self.assertEqual(queries.board_from_url("https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced/job/x"),
                         {"source": "workday", "careers_url": "https://adobe.wd5.myworkdayjobs.com/external_experienced"})
        self.assertIsNone(queries.board_from_url("https://evil-greenhouse.io/stripe"))
        self.assertIsNone(queries.board_from_url("http://boards.greenhouse.io/stripe"))

    def test_queries_include_hashtags(self):
        posts = queries.post_queries(CFG)
        self.assertTrue(any('"#ProductOwner"' in q["query"] and "#bengaluru" in q["query"] for q in posts))
        self.assertTrue(all(q["query"].startswith("site:linkedin.com ") for q in posts))
        self.assertTrue(any('"#remote"' in q["query"] for q in posts))
        self.assertTrue(all("linkedin.com/search/results/content" in u["url"] for u in queries.browser_search_urls(CFG)))


class Posts(unittest.TestCase):
    def test_parse_and_match(self):
        p = feeds.parse_post({"url": "https://www.linkedin.com/posts/jane_hiring-activity-1",
                              "author": "Jane", "author_profile_url": "https://www.linkedin.com/in/jane/",
                              "snippet": "We're #hiring a Senior Product Manager in #Bengaluru #hybrid. "
                                         "Apply https://jobs.lever.co/acme/1 or mail talent@acme.com"})
        self.assertEqual(p.hashtags, ["bengaluru", "hiring", "hybrid"])
        self.assertEqual(p.emails, ["talent@acme.com"])
        self.assertIn("https://jobs.lever.co/acme/1", p.links)
        self.assertTrue(feeds.post_matches(p, CFG))

    def test_rejects_non_linkedin_and_bad_profile(self):
        self.assertIsNone(feeds.parse_post({"url": "https://example.com/post"}))
        p = feeds.parse_post({"url": "https://www.linkedin.com/posts/x", "author_profile_url": "https://evil.test/in/x",
                              "snippet": "hiring product owner"})
        self.assertEqual(p.author_profile_url, "")

    def test_non_hiring_post_ignored(self):
        p = feeds.parse_post({"url": "https://www.linkedin.com/posts/x", "snippet": "My thoughts as a Product Owner"})
        self.assertFalse(feeds.post_matches(p, CFG))


class Outreach(unittest.TestCase):
    def test_validation(self):
        long_note = {"channel": "linkedin_note", "body": "x" * 301, "contact": {}}
        self.assertTrue(any("300" in p for p in outreach.validate(long_note)))
        no_email = {"channel": "email", "body": "Hi", "contact": {"name": "A"}}
        self.assertTrue(any("public email" in p for p in outreach.validate(no_email)))

    def test_page_escapes_and_links(self):
        msgs = [{"company": "Acme", "role": "PM", "channel": "email", "subject": "Hi <b>",
                 "body": "Hello & welcome", "contact": {"name": "<script>x</script>", "email": "a@acme.com"}}]
        page = outreach.render(msgs)
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("mail.google.com/mail/?view=cm", page)
        self.assertIn("Hello &amp; welcome", page)


class Sources(unittest.TestCase):
    """Parsers against canned API payloads (no network)."""

    def test_greenhouse(self):
        payload = {"jobs": [{"id": 1, "title": "Product Owner", "absolute_url": "https://job-boards.greenhouse.io/a/jobs/1",
                             "location": {"name": "Bengaluru"}, "first_published": "2026-10-20T00:00:00Z",
                             "content": "&lt;p&gt;Own the backlog&lt;/p&gt;"}]}
        with mock.patch.object(greenhouse, "fetch_json", return_value=payload):
            js = greenhouse.fetch({"slug": "a", "name": "A"})
        self.assertEqual((js[0].title, js[0].posted, js[0].description), ("Product Owner", "2026-10-20", "Own the backlog"))

    def test_lever(self):
        payload = [{"text": "Senior PM", "hostedUrl": "https://jobs.lever.co/a/1", "createdAt": 1761955200000,
                    "workplaceType": "hybrid", "categories": {"location": "Bangalore"}, "descriptionPlain": "x"}]
        with mock.patch.object(lever, "fetch_json", return_value=payload):
            js = lever.fetch({"slug": "a"})
        self.assertEqual((js[0].work_mode, js[0].location), ("hybrid", "Bangalore"))

    def test_ashby_trusts_workplace_type(self):
        payload = {"jobs": [{"title": "TPM", "jobUrl": "https://jobs.ashbyhq.com/a/1", "isRemote": True,
                             "workplaceType": "Hybrid", "location": "Bengaluru", "publishedAt": "2026-10-30"}]}
        with mock.patch.object(ashby, "fetch_json", return_value=payload):
            js = ashby.fetch({"slug": "a"})
        self.assertEqual(js[0].work_mode, "hybrid")

    def test_workday_url_and_dates(self):
        ep = workday.parse_careers_url("https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced")
        self.assertEqual(ep, {"host": "adobe.wd5.myworkdayjobs.com", "tenant": "adobe", "site": "external_experienced"})
        today = date(2026, 11, 1)
        self.assertEqual(workday.posted_from_label("Posted Today", today), "2026-11-01")
        self.assertEqual(workday.posted_from_label("Posted 3 Days Ago", today), "2026-10-29")
        self.assertIsNone(workday.posted_from_label("Posted 30+ Days Ago", today))

    def test_html_to_text(self):
        self.assertEqual(html_to_text("<p>A &amp; B</p><ul><li>one</li><li>two</li></ul>"), "A & B\none\ntwo")


if __name__ == "__main__":
    unittest.main()


class ResumeFormats(unittest.TestCase):
    def test_xyz_bullet_sentence(self):
        from jobradar.resume import bullet_text
        lead, s = bullet_text({"lead": "Automation", "x": "A bot succeeded 78% of the time",
                               "y": "replaced it with a bulk API", "z": "raising success to 95%"})
        self.assertEqual(lead, "Automation")
        self.assertEqual(s, "A bot succeeded 78% of the time: replaced it with a bulk API, raising success to 95%.")
        self.assertEqual(bullet_text("Plain bullet.")[1], "Plain bullet.")

    def test_all_formats_render_and_escape(self):
        from jobradar.resume import FORMATS, render_html
        data = {"name": "A <b>", "summary": "x & y", "contact": {"email": "a@example.com"},
                "experience": [{"company": "Co", "title": "PM", "dates": "2020-2024",
                                "bullets": [{"x": "p", "y": "s", "z": "o"}]}],
                "skills": [{"group": "G", "items": ["i"]}], "education": [], "metrics": [{"value": "1", "label": "l"}]}
        for fmt in FORMATS:
            html_out = render_html(data, fmt)
            self.assertIn("A &lt;b&gt;", html_out)
            self.assertIn("x &amp; y", html_out)
