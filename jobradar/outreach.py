"""One-click outreach page: every message is a draft the user reviews and sends.

Input (contacts JSON), one object per message, written by the /outreach command:
{
  "company": "Circle", "role": "Senior Product Manager", "job_url": "https://...",
  "contact": {"name": "Jane Doe", "title": "Talent Partner", "source": "post author" | "named in posting" | ...,
              "email": "only if publicly printed in the posting/post/company page",
              "linkedin_url": "https://www.linkedin.com/in/... only if visible on the post"},
  "channel": "email" | "linkedin_note" | "linkedin_message",
  "subject": "...", "body": "..."
}
Nothing here sends anything. Buttons open Gmail/LinkedIn with the text ready, or copy it.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote, urlencode

LINKEDIN_NOTE_LIMIT = 300   # LinkedIn caps connection-request notes at 300 characters


def gmail_compose_url(to: str, subject: str, body: str) -> str:
    return "https://mail.google.com/mail/?" + urlencode({"view": "cm", "fs": "1", "to": to or "",
                                                         "su": subject or "", "body": body or ""})


def mailto_url(to: str, subject: str, body: str) -> str:
    return f"mailto:{quote(to or '')}?subject={quote(subject or '')}&body={quote(body or '')}"


def people_search_url(company: str, keywords: str) -> str:
    return ("https://www.linkedin.com/search/results/people/?keywords="
            + quote(f"{company} {keywords}".strip()) + "&origin=GLOBAL_SEARCH_HEADER")


def validate(msg: dict) -> list[str]:
    problems = []
    body = msg.get("body") or ""
    if not body.strip():
        problems.append("empty message body")
    if msg.get("channel") == "linkedin_note" and len(body) > LINKEDIN_NOTE_LIMIT:
        problems.append(f"LinkedIn note is {len(body)} characters; the limit is {LINKEDIN_NOTE_LIMIT}")
    if msg.get("channel") == "email" and not (msg.get("contact") or {}).get("email"):
        problems.append("email channel but no public email address; use LinkedIn or the company form")
    if "—" in body:
        problems.append("contains an em-dash (style rule)")
    return problems


def _card(i: int, m: dict) -> str:
    c = m.get("contact") or {}
    esc = lambda s: html.escape(str(s or ""), quote=True)
    body, subject = m.get("body") or "", m.get("subject") or ""
    buttons = [f'<button onclick="copyMsg({i})">Copy message</button>']
    if c.get("email"):
        buttons.append(f'<a class="btn" target="_blank" rel="noopener" href="{esc(gmail_compose_url(c["email"], subject, body))}">Open in Gmail</a>')
        buttons.append(f'<a class="btn ghost" href="{esc(mailto_url(c["email"], subject, body))}">Mail app</a>')
    if c.get("linkedin_url"):
        buttons.append(f'<a class="btn" target="_blank" rel="noopener" onclick="copyMsg({i})" href="{esc(c["linkedin_url"])}">Copy + open profile</a>')
    else:
        q = c.get("title") or "recruiter"
        buttons.append(f'<a class="btn ghost" target="_blank" rel="noopener" href="{esc(people_search_url(m.get("company", ""), q))}">Find on LinkedIn</a>')
    if m.get("job_url"):
        buttons.append(f'<a class="btn ghost" target="_blank" rel="noopener" href="{esc(m["job_url"])}">Job posting</a>')
    warn = "".join(f'<p class="warn">{esc(p)}</p>' for p in validate(m))
    count = f"{len(body)} chars" + (f" / {LINKEDIN_NOTE_LIMIT}" if m.get("channel") == "linkedin_note" else "")
    return f"""
<article class="card" id="m{i}">
  <header><div><h2>{esc(c.get('name') or 'Hiring team')}</h2>
  <p class="meta">{esc(c.get('title'))} · {esc(m.get('company'))} · {esc(m.get('role'))}</p>
  <p class="meta">Channel: {esc(m.get('channel'))} · Contact found via: {esc(c.get('source'))} · {count}</p></div>
  <label class="sent"><input type="checkbox" onchange="markSent({i}, this.checked)"> Sent</label></header>
  {f'<p class="subject"><b>Subject:</b> {esc(subject)}</p>' if subject else ''}
  <pre id="body{i}">{esc(body)}</pre>
  {warn}
  <div class="actions">{''.join(buttons)}</div>
</article>"""


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Outreach drafts</title>
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e3de;--accent:#2457d6;--warn:#a4500b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecece8;--muted:#9a9a93;--card:#1f1f1d;--line:#33332f;--accent:#7aa2ff;--warn:#f0a35e}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:24px 16px}} h1{{font-size:22px;margin:0 0 4px}}
.note{{color:var(--muted);margin:0 0 20px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 14px}}
.card.done{{opacity:.55}} header{{display:flex;justify-content:space-between;gap:12px}}
h2{{font-size:17px;margin:0}} .meta{{color:var(--muted);margin:2px 0;font-size:13px}}
pre{{white-space:pre-wrap;font:inherit;background:var(--bg);border-radius:8px;padding:12px;margin:10px 0}}
.actions{{display:flex;flex-wrap:wrap;gap:8px}}
button,.btn{{font:inherit;font-size:14px;border:1px solid var(--accent);background:var(--accent);color:#fff;
border-radius:8px;padding:6px 12px;cursor:pointer;text-decoration:none}}
.btn.ghost{{background:transparent;color:var(--accent)}} .warn{{color:var(--warn);margin:4px 0}}
.sent{{white-space:nowrap;font-size:14px}}
</style></head><body><main>
<h1>Outreach drafts</h1>
<p class="note">Review each message, then send it yourself. Nothing here is sent automatically.
After sending, tell the agent so it can log it in your tracker.</p>
{cards}
</main><script>
function copyMsg(i){{const t=document.getElementById('body'+i).innerText;navigator.clipboard&&navigator.clipboard.writeText(t)}}
function markSent(i,on){{document.getElementById('m'+i).classList.toggle('done',on);
try{{localStorage.setItem('sent-'+location.pathname+'-'+i,on?'1':'')}}catch(e){{}}}}
document.querySelectorAll('.card').forEach((c,i)=>{{try{{if(localStorage.getItem('sent-'+location.pathname+'-'+i)){{c.classList.add('done');c.querySelector('input').checked=true}}}}catch(e){{}}}});
</script></body></html>"""


def render(messages: list[dict]) -> str:
    return PAGE.format(cards="\n".join(_card(i, m) for i, m in enumerate(messages)))


def write_page(contacts_json: str | Path, out_html: str | Path) -> tuple[Path, list[str]]:
    messages = json.loads(Path(contacts_json).read_text(encoding="utf-8"))
    problems = [f"#{i + 1} {p}" for i, m in enumerate(messages) for p in validate(m)]
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(messages), encoding="utf-8")
    return out, problems
