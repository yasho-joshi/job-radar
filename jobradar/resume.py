"""Render a resume in one of three formats (plain, sidebar, sidebar_metric) from one data file.

Data file (JSON), written by /tailor from the profile only:
{
  "name": "Priya Raman", "headline": ["Senior Product Manager", "Payments · Commerce"],
  "contact": {"phone": "...", "email": "...", "location": "...", "linkedin": "linkedin.com/in/..."},
  "summary": "...",
  "metrics": [{"value": "~$80M", "label": "net new ARR"}, ...],          # sidebar_metric shows 4
  "experience": [{"company": "...", "location": "...", "title": "...", "dates": "Sep 2024 - Present",
                  "context": "one line about the product/scope (optional)",
                  "bullets": [{"lead": "Bulk cancellation", "x": "problem", "y": "solution", "z": "outcome"},
                              "a plain string bullet is also accepted"]}],
  "skills": [{"group": "Product", "items": ["Roadmaps", "Prioritization"]}],
  "education": [{"degree": "...", "school": "...", "dates": "2015"}],
  "extras": [{"title": "Languages", "items": ["English (professional)"]}]
}

Bullets follow X-Y-Z: X is the problem, Y the solution, Z the outcome, rendered as one sentence
"X: Y, Z." (e.g. "Bulk cancellations relied on a slow CSV upload: built a real-time cancellation
service, covering 2.6M contracts and saving ~$8M."). Every fact must come from the profile.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

FORMATS = ("plain", "sidebar", "sidebar_metric")
PAGES = {"plain": (1, 2), "sidebar": (1, 2), "sidebar_metric": (1, 2)}   # allowed page counts

esc = lambda s: html.escape(str(s or ""))


def bullet_text(b) -> tuple[str, str]:
    """(lead, sentence) for a bullet. X-Y-Z bullets become 'X: Y, Z.'"""
    if isinstance(b, str):
        return "", b
    x, y, z = (b.get(k, "").strip().rstrip(".") for k in ("x", "y", "z"))
    parts = [p for p in (x, y) if p]
    sentence = ": ".join(parts) if len(parts) == 2 else (parts[0] if parts else "")
    if z:
        sentence = f"{sentence}, {z}" if sentence else z
    return b.get("lead", ""), (sentence + ".") if sentence and not sentence.endswith(".") else sentence


def _bullets(items, bold_lead: bool) -> str:
    out = []
    for b in items:
        lead, text = bullet_text(b)
        if bold_lead and lead:
            out.append(f"<li><b>{esc(lead)}:</b> {esc(text[0].lower() + text[1:] if text else '')}</li>")
        else:
            out.append(f"<li>{esc(text)}</li>")
    return "<ul>" + "".join(out) + "</ul>"


def _contact_line(c: dict, sep: str = " | ") -> str:
    return sep.join(esc(c[k]) for k in ("location", "phone", "email", "linkedin") if c.get(k))


def _experience(d: dict, bold_lead: bool, cls: str = "") -> str:
    out = []
    for e in d.get("experience", []):
        out.append(f"""<div class="job {cls}">
  <div class="row"><span class="co">{esc(e.get('company'))}</span><span class="dt">{esc(e.get('dates'))}</span></div>
  <div class="row"><span class="ti">{esc(e.get('title'))}</span><span class="lo">{esc(e.get('location'))}</span></div>
  {f'<div class="ctx">{esc(e["context"])}</div>' if e.get('context') else ''}
  {_bullets(e.get('bullets', []), bold_lead)}
</div>""")
    return "".join(out)


# ------------------------------------------------------------------ 1. plain
PLAIN_CSS = """
@page { size: A4; margin: 9mm 14mm; }
body { font-family: "Cambria", "Georgia", "Times New Roman", serif; font-size: 9.9pt; line-height: 1.27; color: #111; margin: 0; }
h1 { text-align: center; font-size: 25pt; letter-spacing: 1px; margin: 0 0 2px; font-weight: 700; text-transform: uppercase; }
.contact { text-align: center; font-size: 9.4pt; margin-bottom: 8px; }
h2 { font-size: 12pt; font-weight: 400; letter-spacing: .5px; text-transform: uppercase; border-bottom: 1px solid #222;
     margin: 10px 0 5px; padding-bottom: 1px; }
.row { display: flex; justify-content: space-between; gap: 12px; }
.co { font-weight: 700; } .dt { font-weight: 700; white-space: nowrap; }
.ti, .lo { font-style: italic; } .ctx { font-style: italic; color: #333; }
.job { margin-bottom: 4px; break-inside: avoid-page; }
ul { margin: 2px 0 0; padding-left: 15px; } li { margin: 0 0 1px; }
.skills p { margin: 1px 0; } .edu .row { margin: 1px 0; }
"""


def render_plain(d: dict) -> str:
    skills = "".join(f"<p><b>{esc(s['group'])}:</b> {esc(', '.join(s['items']))}</p>" for s in d.get("skills", []))
    edu = "".join(f'<div class="row"><span>{esc(e["school"])} | {esc(e["degree"])}</span><span>{esc(e.get("dates"))}</span></div>'
                  for e in d.get("education", []))
    extras = "".join(f"<h2>{esc(x['title'])}</h2><p>{esc(', '.join(x['items']))}</p>" for x in d.get("extras", []))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(d['name'])}</title><style>{PLAIN_CSS}</style></head><body>
<h1>{esc(d['name'])}</h1><div class="contact">{_contact_line(d.get('contact', {}))}</div>
<h2>Summary</h2><p style="margin:0">{esc(d.get('summary'))}</p>
<h2>Experience</h2>{_experience(d, bold_lead=False)}
<h2>Skills</h2><div class="skills">{skills}</div>
<h2>Education</h2><div class="edu">{edu}</div>{extras}
</body></html>"""


# ------------------------------------------------------------------ 2. sidebar
SIDEBAR_CSS = """
@page { size: A4; margin: 0; }
html { background: linear-gradient(to right, #1f3a5f 30%, #fff 30%); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font-family: "Arial", "Helvetica", sans-serif; font-size: 9.4pt; line-height: 1.33; color: #1b1b1b; }
.wrap { display: grid; grid-template-columns: 30% 70%; min-height: 297mm; }
aside { color: #fff; padding: 12mm 7mm 10mm 8mm; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
aside h1 { font-size: 22pt; line-height: 1.05; margin: 0 0 8px; text-transform: uppercase; font-weight: 800; }
aside .hl { font-weight: 700; font-size: 10.5pt; text-transform: uppercase; } aside .hl2 { font-size: 9.6pt; opacity: .9; margin-bottom: 10px; }
aside h3 { font-size: 12pt; font-weight: 400; text-transform: uppercase; border-bottom: 1px solid rgba(255,255,255,.7); margin: 12px 0 5px; padding-bottom: 2px; }
aside p, aside li { font-size: 8.8pt; } aside ul { padding-left: 12px; margin: 2px 0 6px; }
aside .grp { font-weight: 700; margin-top: 6px; font-size: 9pt; }
main { padding: 10mm 9mm 9mm 8mm; }
main h2 { color: #1f3a5f; font-size: 15pt; text-transform: uppercase; border-bottom: 2px solid #1f3a5f; margin: 8px 0 5px; padding-bottom: 1px; }
.row { display: flex; justify-content: space-between; gap: 10px; }
.co { font-weight: 700; text-transform: uppercase; } .ti { color: #1f3a5f; font-weight: 700; } .dt, .lo { color: #555; white-space: nowrap; }
.job .row:first-child .dt { order: 2; } .ctx { font-style: italic; color: #555; }
.job { margin-bottom: 6px; break-inside: avoid-page; } ul { margin: 3px 0 0; padding-left: 14px; } li { margin-bottom: 2px; }
.tech p { margin: 2px 0; }
"""


def render_sidebar(d: dict) -> str:
    c = d.get("contact", {})
    head = d.get("headline", [])
    skills = "".join(f'<div class="grp">{esc(s["group"])}</div><ul>' + "".join(f"<li>{esc(i)}</li>" for i in s["items"]) + "</ul>"
                     for s in d.get("skills", []))
    edu = "".join(f'<div class="row"><span><b>{esc(e["degree"])}</b> | {esc(e["school"])}</span><span class="dt">{esc(e.get("dates"))}</span></div>'
                  for e in d.get("education", []))
    extras = "".join(f"<h2>{esc(x['title'])}</h2><p>{esc(', '.join(x['items']))}</p>" for x in d.get("extras", []))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(d['name'])}</title><style>{SIDEBAR_CSS}</style></head><body>
<div class="wrap"><aside>
<h1>{esc(d['name'])}</h1>
{''.join(f'<div class="hl">{esc(h)}</div>' for h in head[:1])}{''.join(f'<div class="hl2">{esc(h)}</div>' for h in head[1:])}
<h3>Contact</h3>{''.join(f'<p style="margin:1px 0">{esc(c[k])}</p>' for k in ('phone','email','location','linkedin') if c.get(k))}
<h3>Summary</h3><p>{esc(d.get('summary'))}</p>
<h3>Skills</h3>{skills}
</aside><main>
<h2>Employment</h2>{_experience(d, bold_lead=False)}
<h2>Education</h2>{edu}{extras}
</main></div></body></html>"""


# ------------------------------------------------------------------ 3. sidebar with metric
METRIC_CSS = """
@page { size: A4; margin: 0; }
html { background: linear-gradient(to right, #16212e 31%, #fff 31%); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font-family: "Segoe UI", "Calibri", "Arial", sans-serif; font-size: 9.6pt; line-height: 1.45; color: #1d2430; }
.page { display: grid; grid-template-columns: 31% 69%; min-height: 297mm; }
aside { color: #e9eef3; padding: 13mm 7mm 10mm 9mm; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
aside h1 { font-size: 23pt; line-height: 1.08; margin: 0 0 8px; color: #fff; }
aside .hl { color: #6fd3b8; font-weight: 600; font-size: 10pt; }
aside .c { font-size: 8.8pt; margin: 3px 0; }
aside h3 { color: #6fd3b8; font-size: 8.6pt; letter-spacing: 1.6px; text-transform: uppercase; margin: 15px 0 4px; }
aside p { margin: 2px 0; font-size: 9pt; }
main { padding: 12mm 9mm 9mm 9mm; }
main h2 { color: #1d7a5f; font-size: 8.8pt; letter-spacing: 1.8px; text-transform: uppercase; margin: 12px 0 6px; }
.metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 10px 0 4px; }
.m { border-top: 2px solid #1d7a5f; padding-top: 5px; } .m b { display: block; font-size: 16pt; }
.m span { font-size: 8pt; color: #4b5563; line-height: 1.25; display: block; }
.row { display: flex; justify-content: space-between; gap: 10px; }
.co { font-weight: 700; font-size: 11pt; } .dt { color: #4b5563; font-size: 8.8pt; white-space: nowrap; }
.ti { font-weight: 600; } .lo { display: none; } .ctx { font-style: italic; color: #4b5563; font-size: 8.8pt; }
.job { margin-bottom: 10px; } ul { margin: 5px 0 0; padding-left: 15px; } li { margin-bottom: 4px; }
"""


def render_sidebar_metric(d: dict) -> str:
    c = d.get("contact", {})
    side = "".join(f"<h3>{esc(s['group'])}</h3>" + "".join(f"<p>{esc(i)}</p>" for i in s["items"]) for s in d.get("skills", []))
    edu = "<h3>Education</h3>" + "".join(f"<p><b>{esc(e['degree'])}</b></p><p>{esc(e['school'])} · {esc(e.get('dates'))}</p>"
                                         for e in d.get("education", []))
    edu += "".join(f"<h3>{esc(x['title'])}</h3>" + "".join(f"<p>{esc(i)}</p>" for i in x["items"]) for x in d.get("extras", []))
    metrics = "".join(f'<div class="m"><b>{esc(m["value"])}</b><span>{esc(m["label"])}</span></div>'
                      for m in d.get("metrics", [])[:4])
    exp = []
    for e in d.get("experience", []):
        e2 = dict(e, company=f"{e.get('company')} · {e.get('location')}" if e.get("location") else e.get("company"))
        exp.append(e2)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(d['name'])}</title><style>{METRIC_CSS}</style></head><body>
<div class="page"><aside>
<h1>{esc(d['name'])}</h1>{''.join(f'<div class="hl">{esc(h)}</div>' for h in d.get('headline', []))}
<div style="height:10px"></div>{''.join(f'<p class="c">{esc(c[k])}</p>' for k in ('phone','email','location','linkedin') if c.get(k))}
{side}{edu}
</aside><main>
<h2>Profile</h2><p style="margin:0">{esc(d.get('summary'))}</p>
{f'<div class="metrics">{metrics}</div>' if metrics else ''}
<h2>Experience</h2>{_experience(dict(d, experience=exp), bold_lead=True)}
</main></div></body></html>"""


RENDER = {"plain": render_plain, "sidebar": render_sidebar, "sidebar_metric": render_sidebar_metric}


def render_html(data: dict, fmt: str) -> str:
    if fmt not in RENDER:
        raise ValueError(f"format must be one of {FORMATS}")
    return RENDER[fmt](data)


def render_pdf(data: dict, fmt: str, out_pdf: str | Path, png: str | Path | None = None) -> int:
    """Write the PDF (and optionally a PNG preview of page 1). Returns the page count."""
    from playwright.sync_api import sync_playwright
    page_html = render_html(data, fmt)
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 794, "height": 1123})
        pg.set_content(page_html, wait_until="load")
        pg.pdf(path=str(out_pdf), format="A4", print_background=True, prefer_css_page_size=True)
        if png:
            pg.screenshot(path=str(png), full_page=False)
        b.close()
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(out_pdf)).pages)
    except Exception:
        return -1


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
