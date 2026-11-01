# /track - Applications, outcomes and follow-ups

Tracker: `data/tracker.csv` (create with this header if missing):
`date,company,role,source,status,fit,notes,cv_file,cover_file,job_url,deadline`

Statuses: `drafted` -> `applied` -> `interview` -> `offer` -> `hired`; final: `hired`, `rejected`, `no_response`,
`offer_declined`, `withdrawn`. Notes never contain commas or line breaks (use `;`).

`$ARGUMENTS`:
- nothing: list open applications (days since last activity, follow-ups sent, deadline with a warning inside 7 days)
- `<company> applied|interview|rejected|...`: update that row. Moving off `drafted` sets `date` to the real
  submission date (ask if unknown; never assume silently). Copy the submitted CV / cover letter and the cleaned
  posting into `data/applications/<company>_<role>/` and keep an `outcome.md` (stages reached, dated notes).
- `followup`: for applications quiet 10+ days with fewer than two follow-ups, draft a 60-120 word note grounded in
  the submitted documents, build it with `/outreach`'s page if there is a contact, and log only after the user sends.
- `stale`: list applications quiet 60+ days and ask before marking any `no_response`.

Never rewrite history: append dated notes, keep earlier files as submitted.
