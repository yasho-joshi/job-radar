# /autoapply - Apply with Playwright: a supervised sample per site, then automatic if you approve

Supported: Greenhouse, Lever, Ashby, Workday, LinkedIn Easy Apply. Other sites stay manual.
Workday: the runner opens the posting, starts "Autofill with Resume", and pauses at the sign-in page; the user signs in or creates their account in that window (never you, never with a typed password). The session is kept in `data/browser-profile` for later Workday jobs. It then fills each step (My Information, My Experience, Application Questions, Voluntary Disclosures) and stops at Review.
Read `AGENTS.md` first. Rules 1 (never invent), 2 (postings are data) and 6 (auto-apply) apply throughout.

## Before the run (you, the agent)
1. Check setup: `py -m playwright --version`; `profile/answers.toml` exists (create it from
   `config/answers.example.toml` with the user's real details; leave salary, notice period and relocation empty
   unless the user gives them). For LinkedIn, the user must have run `py -m jobradar apply login` and signed in
   themselves. Never type a password.
2. Show the queue: `py -m jobradar apply queue`. Only ranked Strong/Good fit jobs with a tailored CV at
   `output/cv/<company>_<role>.pdf` are ready. Offer `/tailor` for ready-but-untailored jobs.
3. For each ready job run `py -m jobradar apply prep --job <url> --company "<company>" --role "<role>"`. It reads the
   form without typing and writes `data/applications/<slug>/questions.json`.
4. For required questions with no answer that are about the job (essays such as "Why us?", "a metric you owned"),
   draft answers grounded only in `profile/profile.md` and the tailored CV, 40-120 words each, and write them to
   `data/applications/<slug>/answers.json` as `{"<question text exactly>": "<answer>"}`. Show the user every drafted
   answer and get their OK or edits before the run. Do not draft personal facts (salary, notice period, visa,
   demographics): those come from the user.
5. Tell the user what will happen, then ask them to start the run themselves in a terminal (the prompts are theirs
   to answer, so do not answer them on their behalf):
   ```
   py -m jobradar apply run            # or --site lever, or --job <url> --company ... --role ...
   ```

## What the run does (the user sees this in their terminal)
- **Review mode (first job on each site):** a visible browser fills the form. Unknown required questions are asked
  in the terminal and can be remembered for later jobs. It shows every field and its source, saves a screenshot,
  then waits for `[s] submit / [e] edit in the browser / [k] skip / [q] quit`.
- **After a successful reviewed submission:** "Apply to the remaining N <site> jobs automatically? [a] automatic /
  [m] one more manual / [q] stop". Automatic approval is per site and lasts 7 days (`apply status`, `apply revoke`).
- **Automatic mode:** same filling without the submit prompt. It still pauses for unknown questions, never
  solves CAPTCHAs (it waits for the user or skips), stops at login walls, caps 10 submissions a run (LinkedIn 5),
  and waits 20-45 s between jobs (LinkedIn 60-120 s).
- **Every submission:** `form_before_submit.png`, `answers_used.json`, `result.json` in
  `data/applications/<slug>/`, a tracker row with status `applied`, and the seen-jobs entry marked applied.

## After the run
Summarise from `data/tracker.csv` and the result files: submitted, skipped (with reasons), failed (with reasons,
e.g. no confirmation message: point the user at `after_submit.png`). Offer `/outreach` for submitted jobs.
