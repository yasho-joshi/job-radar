# /outreach - Contacts who invited contact, drafted messages, one-click page

`$ARGUMENTS`: a job (URL, tracker company, or table number). Read `AGENTS.md` rules 1, 3 and 4 first.
The output is drafts. The user presses send.

## 1. Find contacts (best available, in this order)
1. The author of a `#hiring` post for this role (`data/posts.jsonl`, or a new search:
   `site:linkedin.com/posts "#hiring" "<role>" "<company>"`). They asked for replies.
2. A recruiter or hiring manager named in the posting itself.
3. An email address printed in the posting, the post, or the company's own careers / contact page.
4. Nobody named: the company's recruiting team via the posting's apply flow, plus LinkedIn people-search links
   ("<company> recruiter", "<company> <team> product") for the user to browse. You do not open those results.

Never guess an email pattern, never look people up across other sites, never visit profiles in bulk. Record for each
contact where you found them (`source`). Check `data/outreach.jsonl` first and skip anyone already messaged for this
company in the last 30 days unless the user says otherwise.

## 2. Draft one message per contact
Ground every claim in the CV and cover letter tailored for this job (or `profile/profile.md` if none exists).
- **LinkedIn connection note:** at most 300 characters. Role, one concrete match, a question.
- **LinkedIn message / reply to a post:** 60-120 words.
- **Email:** subject that names the role; 90-150 words; one quantified match; one honest line on fit; a clear,
  low-pressure ask (a short call, or who owns hiring); signature with phone and LinkedIn.
Style rules from `AGENTS.md`. No attachments claimed unless the user will attach them.

## 3. Build the one-click page
Write the messages to `output/outreach/<company>_<role>.json` (schema in `jobradar/outreach.py`), then:
```
py -m jobradar outreach-page --in output/outreach/<company>_<role>.json --out output/outreach/<company>_<role>.html
```
Fix every warning it prints (note over 300 characters, email channel without a public address, em-dashes). Open the
page for the user. Each card has: Copy message, Open in Gmail (prefilled), Copy + open profile, Find on LinkedIn,
Job posting, and a Sent checkbox.

## 4. Optional Gmail drafts
If a Gmail connector is available and the user says yes for this batch, create drafts (never send) for the email
contacts, then tell them the drafts are in Gmail's Drafts folder.

## 5. Log
When the user says they sent a message, append to `data/outreach.jsonl`:
`{"date", "company", "role", "contact_name", "contact_source", "channel"}` and add `outreach <channel> <date>` to the
tracker row's notes. Log nothing for messages they did not send. Suggest a follow-up only after 7+ days and at most
once per contact.
