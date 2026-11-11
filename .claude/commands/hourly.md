# /hourly - Scheduled run: new jobs only, ranked, researched, de-duplicated

The prompt for an hourly scheduled task. Read `AGENTS.md` first. Windows: use `py`.
Unattended: never apply, never draft or send email, never edit `profile/`. Keep the run short.

1. `py -m jobradar scan --linkedin --incremental`. If it prints "no new jobs since the last run", stop and
   report one line ("No new jobs since HH:MM"). Do not rank, research or check Gmail.
   Web-search discovery and `#hiring` posts (`/radar` steps 2-3) are not part of the hourly run.
2. Run `/rank` on the run file the scan wrote (steps 1-6 there): it scores only the new jobs, researches
   AmbitionBox for new candidates above match 80 (cached 7 days, so most hours fetch nothing), and checks Gmail.
3. `py -m jobradar shortlist`. Report only when the top 5 changed since the previous shortlist file in
   `data/runs/`: the new entries with score, recommendation and the page link. Otherwise one line.
4. Delete `data/tmp/` files.

Applying stays with the user: `py -m jobradar apply shortlist --pick N` in their own terminal, after `/tailor`.
