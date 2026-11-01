# Third-party notices

job-radar includes or adapts material from the following MIT-licensed projects. Their license texts are in
`third_party/`.

## ai-job-search (MIT, Copyright (c) 2026 Mads Lorentzen)
https://github.com/ai-job-search-dev/ai-job-search
- `tools/posting_guard.py`, `tools/page_decode.py`, `tools/verify_pdf.py`, `tools/verify_layout.py`,
  `tools/fetch_page.py`, `tools/robots_check.py` (copied unchanged)
- `tools/linkedin-search/` (LinkedIn public job CLI, TypeScript; copied unchanged)
- `templates/cover/` (`cover.cls`, cover letter template). The bundled Lato and Raleway fonts are under the
  SIL Open Font License 1.1: `third_party/OFL-Lato.txt`, `third_party/OFL-Raleway.txt`
- `profile.example/cv.tex` (moderncv master CV template, lightly edited)
- `.claude/agents/posting-scorer.md`, `.claude/agents/application-reviewer.md` and the `/tailor` workflow
  (adapted from its `/apply`, `/rank` and agent definitions)

## career-ops (MIT, Copyright (c) 2026 Santiago Fernández de Valderrama)
https://github.com/santifer/career-ops
- The public ATS endpoints and their quirks used in `jobradar/sources/` (Greenhouse board API, Lever postings API,
  Ashby posting API with `workplaceType` over `isRemote`, Workday CXS search and relative "Posted N Days Ago" dates).
  The Python clients are new code informed by career-ops' providers.
