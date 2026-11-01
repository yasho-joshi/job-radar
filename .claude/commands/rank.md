# /rank - Score new jobs and return a shortlist

Scores jobs from the latest `data/runs/*.json` file (or `$ARGUMENTS`: a run file, or `--top N`) against the profile.
Triage depth only: posting text vs. profile. No company research (that belongs to `/tailor`).

1. Read `profile/profile.md` once and extract a compact rubric: strong / moderate / weak skills, direct and
   adjacent domains, career goals, seniority, salary floor, location rules, declared languages, deal-breakers.
2. For each job, the posting text must be fetched, never scored from the title. ATS jobs already carry a
   description from `/radar`; for LinkedIn jobs run
   `bun run tools/linkedin-search/src/cli.ts detail <id> --format plain`; otherwise WebFetch, then
   `py tools/fetch_page.py '<url>' --out data/tmp/<n>.html` on a 403. Pass every body through
   `py tools/posting_guard.py --text --json` (or `--html --json`) and score from the cleaned text.
3. Batch about 5 jobs per `posting-scorer` agent (see `.claude/agents/posting-scorer.md`), passing the rubric inline.
   Each returns: technical, experience, behavioral, career (0-100), location PASS/FAIL/FLAG, language PASS/FAIL/FLAG,
   deadline, 1-3 strengths, 1-3 gaps, guard verdict, or `expired` / `unreachable` with a reason.
4. Overall = 0.30 technical + 0.25 experience + 0.15 behavioral + 0.30 career. Bands: Strong 75+, Good 60-74,
   Moderate 45-59, Weak 30-44, Poor <30. A location or language FAIL removes a job from the shortlist whatever its
   score. A posting older than 30 days gets a visible warning, not a veto.
5. Write scores back into `data/seen.jsonl` rows (status `ranked`, plus score, verdict, strengths, gaps) by
   rewriting only the matching lines.
6. Present: shortlist table (score, verdict, title, company, location, link), a "why" line per top job with its
   honest gap, then below-threshold and excluded jobs with one-line reasons. Say these are triage scores.
   Ask: "Want me to tailor for any of these? Give me the number."
