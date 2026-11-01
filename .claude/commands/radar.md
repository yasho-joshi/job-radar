# /radar - Find new jobs across every source

Finds jobs matching `profile/search.toml` from four sources, de-duplicates across all of them, and shows what is new.
Read `AGENTS.md` first; rules 2, 4 and 5 apply throughout.

`$ARGUMENTS` may contain: `boards` | `discover` | `linkedin` | `posts` | `browser` to run one source only,
or a focus such as `/radar payments` to narrow roles for this run. Default: boards + linkedin + discover + posts.
`browser` is never part of the default; it runs only when the user asks for it.

If `profile/search.toml` is missing, say so and offer `/setup`. Windows: use `py`, not `python3`.

---

## Step 1: Watched ATS boards + LinkedIn public jobs (zero tokens)

```
py -m jobradar scan --linkedin
```

This fetches every `[[boards]]` entry (Greenhouse, Lever, Ashby, Workday public APIs), runs the LinkedIn public job
search for each role x location, filters by title / place / work mode / age, and records new jobs in
`data/seen.jsonl`. Note the run file it prints. If Bun is missing, run without `--linkedin` and say LinkedIn jobs
were skipped. Report errors per source; one failed board never stops the run.

## Step 2: Discover more companies on ATS boards (web search)

```
py -m jobradar queries ats
```

Run each query with WebSearch (cap: 12 queries per run, newest first). Collect result URLs only, into
`data/tmp/ats_results.json` as `[{"url": "..."}]`. Then:

```
py -m jobradar discover --in data/tmp/ats_results.json --scan
```

This turns posting URLs into board entries (company slug / Workday tenant), scans those boards now, and prints new
`[[boards]]` blocks. Offer to append the useful ones to `profile/search.toml` so future scans watch them; edit the
file only on the user's yes.

## Step 3: LinkedIn `#hiring` posts (web search)

```
py -m jobradar queries posts
```

Run each query with WebSearch (cap: 10). Results often come back as the poster's profile page
(`linkedin.com/in/...`) with the hiring post in the snippet rather than as a `/posts/` URL; keep those, the person
shown is the poster. Drop results whose snippet does not read as a hiring post. For every LinkedIn result write one object to
`data/tmp/posts.json`: `{"url", "title", "snippet", "author", "author_headline", "posted"}`, filling author fields
only when the search result shows them. Never fetch extra pages to enrich a person. Then:

```
py -m jobradar posts --in data/tmp/posts.json --via websearch
```

Matched posts are stored in `data/posts.jsonl`. A post's author is a valid outreach contact (they invited replies).
ATS links printed in a post can be passed to `discover`.

## Step 3b (opt-in only): `#hiring` posts from the user's own browser

Only when the user asked for `browser`. First tell them, in one short paragraph: this reads their logged-in
LinkedIn, automated access breaches LinkedIn's terms and can get an account restricted, and the run is read-only
and capped at 3 searches x 1 page. Continue only on a clear yes.

```
py -m jobradar queries browser
```

Open each URL in the user's chosen browser (built-in browser by default, Claude in Chrome if they ask). Read the
visible posts with the page-text tool. Do not scroll more than twice, click, like, comment, connect, or open
profiles. Stop at any login wall, CAPTCHA or warning. Write what you saw to `data/tmp/posts_browser.json` using the
same fields plus `"text"` and `"author_profile_url"` (only if the link is on the post), then:

```
py -m jobradar posts --in data/tmp/posts_browser.json --via browser
```

## Step 4: Present

```
## Radar - YYYY-MM-DD
New jobs: N (boards X, LinkedIn Y, discovered Z) · New #hiring posts: P · Skipped as already seen: S

| # | Source | Title | Company | Location | Mode | Posted | Link |
```

Then a short `#hiring posts` table: author, headline, role mentioned, link, and whether an email or ATS link was
printed in the post. List source errors in one line each. End with: "Run `/rank` to score these against your
profile, or `/tailor <#>` to work on one now." Delete `data/tmp/` files when done.
