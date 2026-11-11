# job-radar

Find jobs across company ATS boards and LinkedIn, tailor your CV honestly, and send one-click outreach you
review yourself. Local-first, runs inside an AI coding agent (Claude Code, Codex, OpenCode...).

## What it does

| Step | How |
|---|---|
| **Search** | Public Greenhouse, Lever, Ashby and Workday APIs for companies you watch; web-search discovery of new companies on those systems; LinkedIn's public job search; LinkedIn `#hiring` posts by role, place and `#remote` / `#hybrid` |
| **De-dupe** | One role seen on LinkedIn, the company ATS and a `#hiring` post counts once (the ATS copy wins) |
| **Rank** | Scores each posting against your profile: skills, experience, culture, career fit, location and language gates |
| **Tailor** | Fit check, then a CV and cover letter built only from your profile, a reviewer pass that audits every fact, LaTeX compile, page/layout/ATS checks |
| **Outreach** | Finds the best contact who invited contact (post author, named recruiter, published address), drafts the message, and builds a page with Copy, Open in Gmail and Open on LinkedIn buttons |
| **Auto-apply** | Playwright fills and submits Greenhouse, Lever, Ashby, Workday and LinkedIn Easy Apply forms (on Workday you sign in yourself when it asks). The first job on each site is a supervised sample you approve in the terminal; then you choose automatic for the rest, one more manual, or stop |
| **Track** | Applications, outcomes, polite follow-ups (max two) |

## Ground rules

1. **Never invent experience.** Every claim traces to `profile/`. Gaps are stated, with an honest bridge.
2. **Postings are data, not instructions.** Fetched text goes through `tools/posting_guard.py`.
3. **You send.** job-radar drafts messages; it never sends them, connects or likes for you. Applications are
   submitted only by the auto-apply runner you start, after you approve a sample per site.
4. **People's data is respected.** No guessed emails, no bulk profile scraping.
5. **Gentle with platforms.** Public APIs at normal volume; LinkedIn browser mode is opt-in, read-only and capped,
   and you are warned that automated LinkedIn access breaches its terms.

## Your data stays local

`profile/` (your profile, search config, master CV), `data/` (seen jobs, posts, tracker, archive) and `output/`
(tailored documents, outreach pages) are in `.gitignore`. Only the tool itself is in git.

## Install

- Python 3.11+ (standard library only; `pip install pypdf` for PDF text checks)
- [Bun](https://bun.sh) for the LinkedIn job CLI: `winget install Oven-sh.Bun`, then `cd tools/linkedin-search && bun install`
- LaTeX: MiKTeX (Windows), MacTeX or TeX Live. CV uses `lualatex`, cover letter `xelatex`
- An agent CLI, e.g. `npm install -g @anthropic-ai/claude-code`

```
git clone https://github.com/y2j-xdr/job-radar.git && cd job-radar
claude          # then run /setup
```

## Use

```
/setup                 build profile/ from your CV (or import an ai-job-search / career-ops workspace)
/radar                 find new jobs from every source   (/radar browser = opt-in logged-in LinkedIn posts)
/rank                  score them and get a shortlist
/tailor 3              fit check + tailored CV and cover letter for job #3
/outreach 3            contacts + drafted messages + one-click page
/autoapply             prepare the queue and per-job answers, then run the applier yourself:
/track Acme applied    record progress; /track followup drafts polite nudges
```

### Resume formats

Three formats render from one resume data file, with bullets written as X-Y-Z (problem, solution, outcome):
**plain** (single column, serif), **sidebar** (navy left column with contact, summary and skills) and
**sidebar_metric** (dark sidebar plus a strip of four headline numbers). `/setup` shows samples with made-up data
and saves your default; `/tailor` asks whether to keep or change the format for each role type.

```
py -m jobradar resume --samples                                    # previews in config/resume_samples/
py -m jobradar resume --data output/resume/acme_pm.json --format sidebar --out output/cv/acme_pm.pdf
```

### Auto-apply

```
py -m pip install playwright && py -m playwright install chromium
cp config/answers.example.toml profile/answers.toml      # your real answers; empty = asked during the run
py -m jobradar apply login        # LinkedIn only: sign in yourself in the window that opens
py -m jobradar apply queue        # what is ready (Strong/Good fit + tailored CV) and why others are skipped
py -m jobradar apply prep --job <url> --company "<co>" --role "<role>"   # read-only: list the form's questions
py -m jobradar apply run          # review a sample per site, then choose automatic / one more manual / stop
py -m jobradar apply status       # which sites are automatic (approval lasts 7 days); `apply revoke` turns it off
```

Safeguards: answers only from your answer file, answers you give during the run, or per-job answers you approved
(never guessed); demographic questions get "decline to self-identify" by default; at most 10 submissions a run
(LinkedIn 5) with pauses between jobs; pauses on any CAPTCHA or login wall and never solves them; never creates
accounts or types passwords (on Workday it pauses so you sign in yourself); a screenshot and the answers used are saved for every submission.
LinkedIn Easy Apply automation breaches LinkedIn's terms and can get your account restricted; it is opt-in by site.

The Python tools also work on their own:

```
py -m jobradar scan --linkedin           # watched boards + LinkedIn public jobs
py -m jobradar queries posts             # #hiring search queries for your agent's web search
py -m jobradar discover --in urls.json --scan
py -m jobradar outreach-page --in contacts.json --out output/outreach/acme_pm.html
py -m unittest discover -s tests         # offline tests
```

## Configure

Copy `config/search.example.toml` to `profile/search.toml` (or let `/setup` do it): roles, excluded titles,
places, accepted countries, work modes, LinkedIn place strings, hashtags, and `[[boards]]` for companies to watch.

## Credits

Built on ideas and code from two MIT-licensed projects:
[ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) (fact-grounded tailoring workflow, posting guard,
PDF checks, LinkedIn job CLI, LaTeX templates) and [career-ops](https://github.com/santifer/career-ops) (public ATS
endpoints and their quirks). See `NOTICE.md`. Licensed MIT.
