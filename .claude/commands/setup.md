# /setup - Build your profile and search config

Creates `profile/` (gitignored): `profile.md`, `search.toml`, `cv.tex`. Templates are in `profile.example/`
and `config/search.example.toml`.

## 1. Import or start fresh
Ask which applies:
- **A. Existing workspace:** the user names a folder from ai-job-search or career-ops. Read its profile files
  (`CLAUDE.md` + `.claude/skills/job-application-assistant/01-candidate-profile.md`, or `cv.md` +
  `config/profile.yml`) and its master CV, and map them into `profile/profile.md` and `profile/cv.tex`.
- **B. A CV file:** a PDF, DOCX or pasted text. Extract it (`pypdf` for PDFs).
- **C. Interview:** ask section by section (identity, languages and levels, experience, skills, goals, deal-breakers).

Show what you extracted and ask only for gaps: target roles (function first, then several titles), seniority,
languages with honest levels, locations and work modes, visa needs, salary floor, deal-breakers, target companies.
Suggest one or two adjacent role types the profile supports.

## 2. Write the files
- `profile/profile.md` from `profile.example/profile.md`. Facts only; mark inferred traits as inferred.
- `profile/cv.tex` from `profile.example/cv.tex` (moderncv). Single-hyphen date ranges. Compile once with lualatex
  to confirm it builds.
- `profile/search.toml` from `config/search.example.toml`: roles, exclude list, locations, `also_accept`, work
  modes, LinkedIn place strings, place and mode hashtags. For target companies, find their ATS board (search the
  company's careers page; accept only Greenhouse, Lever, Ashby or Workday URLs) and add `[[boards]]` entries.

## 3. Confirm
List the files, remind the user that `profile/`, `data/` and `output/` never enter git, and suggest `/radar`.
