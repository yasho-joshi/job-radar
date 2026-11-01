# /tailor - Honest fit check, then a tailored CV and cover letter

`$ARGUMENTS`: a job URL, a number from the last `/rank` or `/radar` table, or pasted posting text.
Adapted from ai-job-search's `/apply` drafter-reviewer workflow (MIT, Mads Lorentzen).

## 1. Get the posting
Fetch it (LinkedIn: the CLI `detail` command; ATS: the stored description or WebFetch; 403: `tools/fetch_page.py`;
pasted: save to `data/tmp/posting.txt`). Run `tools/posting_guard.py`; show its verdict first and ask before
continuing if it is not clean. Prefer the employer's own ATS copy over an aggregator; note any differences (level,
requisition ID). Extract company, role, team, location, deadline, posting language.

## 2. Fit evaluation (show it, then ask)
Score technical, experience, behavioral, career (0-100) and location / language / eligibility gates, with a
requirement-by-requirement table: matched, partial, gap. Recommend apply / apply with caveats / skip, then ask:
"Should I draft the CV and cover letter?" Stop on no.

## 3. Draft
- Sources of truth: `profile/profile.md`, `profile/cv.tex`. Nothing else, not earlier tailored CVs.
- CV: copy `profile/cv.tex` to `output/cv/<company>_<role>.tex`. Rewrite the profile statement and reorder bullets
  for this posting; use the posting's own terms only where the work truly matches (interview backtrack test:
  could the user explain this line without "well, actually..."?). Date ranges use a single ASCII hyphen
  (`2019-2024`), never `--`. Exactly 2 pages.
- Cover letter: `templates/cover/` (`cover.cls`, fonts) to `output/cover/<company>_<role>.tex`, in the posting's
  language, 250-300 words, one page. Open with the role and the strongest match; one paragraph on what the company
  is doing (each claim verified on the company's own site); 3-4 evidence bullets; an honest gap paragraph.
- Optional: if the user prefers their own resume style skill (for example a `sidebar-metric-resume` skill), use it
  for the CV instead, with the same grounding rules.

## 4. Review
Dispatch `application-reviewer` (`.claude/agents/application-reviewer.md`) with both drafts and the posting inline.
It researches the company from its official site, audits every date, title and number against the profile, and
returns exact-string edits plus notes. Apply edits that are grounded; verify any company claim yourself before use;
save its research to `data/company_research/<company>.json`.

## 5. Compile and check (never skip)
```
cd output/cv && lualatex -interaction=nonstopmode <file>.tex
cd output/cover && xelatex -interaction=nonstopmode <file>.tex   (copy cover.cls + OpenFonts next to it first)
py tools/verify_pdf.py output/cv/<file>.pdf --pages 2 --ascii-dates --dump-text output/cv/<file>.txt
py tools/verify_pdf.py output/cover/<file>.pdf --pages 1
py tools/verify_layout.py output/cv/<file>.pdf
```
Fix and recompile until clean. If a page is too empty, restore real content from the profile; never pad. Check the
text dump for email and phone as text, and report a keyword table: covered / synonym only / missing (have it) /
missing (gap). Never stuff a keyword the profile does not support. Delete `.aux .log .out .txt`.

## 6. Present
Pass/fail checklist, key tailoring choices, any "stretch" lines for the user to keep / soften / drop, file paths.
Add a tracker row with status `drafted` (see `/track`). Offer `/outreach` for this job.
