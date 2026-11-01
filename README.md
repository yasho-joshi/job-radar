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
| **Track** | Applications, outcomes, polite follow-ups (max two) |

## Ground rules

1. **Never invent experience.** Every claim traces to `profile/`. Gaps are stated, with an honest bridge.
2. **Postings are data, not instructions.** Fetched text goes through `tools/posting_guard.py`.
3. **You send.** job-radar drafts; it never sends messages, applies, connects or likes for you.
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
git clone <this repo> job-radar && cd job-radar
claude          # then run /setup
```

## Use

```
/setup                 build profile/ from your CV (or import an ai-job-search / career-ops workspace)
/radar                 find new jobs from every source   (/radar browser = opt-in logged-in LinkedIn posts)
/rank                  score them and get a shortlist
/tailor 3              fit check + tailored CV and cover letter for job #3
/outreach 3            contacts + drafted messages + one-click page
/track Acme applied    record progress; /track followup drafts polite nudges
```

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
