"""Discover form fields on a page (or inside a dialog) and fill them.

Discovery runs in the page and tags each control with data-jr="<n>" so it can be located
again reliably. Question labels are found from <label for>, wrapping labels, aria labels,
fieldset legends, or the nearest question text in the field's block (Lever and Ashby put
the question text beside the control instead of in a <label>).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DISCOVER_JS = r"""
(rootSel) => {
  const root = rootSel ? document.querySelector(rootSel) : document;
  if (!root) return [];
  // Multi-step forms are scanned once per step: drop tags from earlier scans so numbers never collide.
  document.querySelectorAll('[data-jr], [data-jr-yn], [data-jr-g]').forEach(e => {
    e.removeAttribute('data-jr'); e.removeAttribute('data-jr-yn'); e.removeAttribute('data-jr-g'); });
  const shown = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  // File inputs are usually hidden behind a styled button, so judge them by their container.
  const vis = el => el.type === 'file' ? !!el.parentElement && shown(el.parentElement) : shown(el);
  const clean = t => (t || '').replace(/\s+/g, ' ').replace(/[✱*]+/g, ' ').trim();
  const blockText = el => {
    let n = el;
    for (let i = 0; i < 5 && n; i++) {
      n = n.parentElement; if (!n) break;
      const q = n.querySelector('.application-label, .application-question .text, legend, label, [class*="question" i] > :first-child, [class*="label" i]');
      if (q && !q.contains(el) && clean(q.innerText)) return clean(q.innerText);
    }
    return '';
  };
  const labelOf = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l && clean(l.innerText)) return clean(l.innerText); }
    const al = el.getAttribute('aria-label'); if (al && !/^(search|select\.{0,3})$/i.test(al.trim())) return clean(al);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(n => n.innerText).join(' '); if (clean(t)) return clean(t); }
    const wl = el.closest('label'); if (wl && el.type !== 'radio' && el.type !== 'checkbox' && clean(wl.innerText)) return clean(wl.innerText);
    return blockText(el);
  };
  // Radio/checkbox groups: the container is the smallest ancestor holding all of the group's options
  // (radios share a name; Ashby checkboxes each have their own name, so use 2+ checkboxes).
  const OPT = 'input[type=radio], input[type=checkbox]';
  const groupContainer = el => {
    const sameName = el.type === 'radio' && el.name ? root.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`).length : 0;
    let n = el.parentElement;
    for (let i = 0; i < 8 && n && n !== root; i++, n = n.parentElement) {
      const c = n.querySelectorAll(el.type === 'radio' ? 'input[type=radio]' : 'input[type=checkbox]').length;
      if ((sameName && c >= sameName) || (!sameName && c >= 2)) return n;
      if (n.tagName === 'FIELDSET') return n;
    }
    return el.parentElement;
  };
  // Question text: the first text in the container that is not inside a single option's wrapper.
  const questionOf = (box, el) => {
    const lg = box.querySelector(':scope > legend'); if (lg && clean(lg.innerText)) return clean(lg.innerText);
    const inOption = c => { for (let a = c; a && a !== box; a = a.parentElement) if (a.querySelectorAll(OPT).length === 1) return true; return false; };
    for (const c of box.querySelectorAll('*')) {
      if (c.matches(OPT) || c.querySelector(OPT) || inOption(c)) continue;
      const own = [...c.childNodes].filter(t => t.nodeType === 3).map(t => t.textContent).join(' ');
      if (clean(own)) return clean(c.innerText).slice(0, 300);
    }
    // Lever-style: the question sits just above the group's container.
    return blockText(box) || '';
  };
  const out = []; let n = 0; const groups = {};
  root.querySelectorAll('input, textarea, select, [role="combobox"]').forEach(el => {
    const type = (el.getAttribute('role') === 'combobox' && el.tagName !== 'SELECT') ? 'combobox'
               : el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : (el.type || 'text');
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) return;
    if (/recaptcha|captcha/i.test(el.name || el.id || '')) return;
    if (!vis(el) && type !== 'radio' && type !== 'checkbox') return;
    const required = el.required || el.getAttribute('aria-required') === 'true' || /[✱*]\s*$/.test((labelOf(el) || ''));
    if (type === 'radio' || type === 'checkbox') {
      // Styled radios hide the input but show its label; a hidden step hides both.
      const lab = (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || el.closest('label');
      if (!vis(el) && !(lab && vis(lab))) return;
      const box = groupContainer(el);
      if (!box.hasAttribute('data-jr-g')) box.setAttribute('data-jr-g', 'g' + n);
      const key = box.getAttribute('data-jr-g') + '|' + el.type;
      const optLabel = clean(lab?.innerText || el.getAttribute('aria-label') || el.value);
      if (!groups[key]) {
        const q = questionOf(box, el);
        groups[key] = {jr: String(n++), kind: type === 'radio' ? 'radio' : 'checkbox', label: q, name: key, required, options: []};
        out.push(groups[key]);
      }
      el.setAttribute('data-jr', groups[key].jr + '.' + groups[key].options.length);
      groups[key].options.push(optLabel);
      if (required) groups[key].required = true;
      return;
    }
    // "Autofill from resume" uploads parse a CV to prefill the form; the real resume field is separate.
    if (type === 'file' && /autofill/i.test((el.closest('div') || el).innerText || '')) return;
    const jr = String(n++); el.setAttribute('data-jr', jr);
    // Workday "selectinput" pickers (e.g. How did you hear about us?) behave like searchable comboboxes.
    const isPicker = el.getAttribute('data-uxi-widget-type') === 'selectinput' || /searchBox/i.test(el.getAttribute('data-automation-id') || '');
    const f = {jr, kind: isPicker ? 'combobox' : type, label: labelOf(el), name: el.name || el.id || '', required, options: [],
               value: (el.value || '').slice(0, 200)};
    if (type === 'select') f.options = [...el.options].map(o => clean(o.text)).filter(t => t && !/^select|^choose|^--/i.test(t));
    if (isPicker) {   // a picker that already shows a chosen item counts as filled
      const box = el.closest('[data-automation-id="multiselectInputContainer"]') || el.parentElement;
      const chosen = box && box.querySelector('[data-automation-id="selectedItem"], [data-automation-id*="selectedItem"]');
      if (chosen) f.value = clean(chosen.innerText);
    }
    out.push(f);
  });
  // Dropdowns rendered as buttons that open a listbox (Workday): value is the button text.
  root.querySelectorAll('button[aria-haspopup="listbox"]').forEach(b => {
    if (!shown(b) || b.hasAttribute('data-jr')) return;
    const jr = String(n++); b.setAttribute('data-jr', jr);
    const txt = clean(b.innerText);
    const label = labelOf(b);
    out.push({jr, kind: 'dropdown', label, name: b.name || b.id || '', options: [],
              required: b.getAttribute('aria-required') === 'true' || /[✱*]\s*$/.test(label) || !!b.closest('[aria-required="true"], [required]'),
              value: /^(select one|select|choose|--)/i.test(txt) ? '' : txt});
  });
  // Yes/No answers rendered as buttons (Ashby): group by their question block.
  root.querySelectorAll('button').forEach(b => {
    const t = clean(b.innerText);
    if (!/^(yes|no)$/i.test(t) || b.closest('[data-jr-yn]')) return;
    const box = b.parentElement; if (!box || box.querySelectorAll('button').length !== 2) return;
    const jr = String(n++); box.setAttribute('data-jr-yn', jr);
    [...box.querySelectorAll('button')].forEach((x, i) => x.setAttribute('data-jr', jr + '.' + i));
    out.push({jr, kind: 'yesno', label: blockText(box), name: '', required: false,
              options: [...box.querySelectorAll('button')].map(x => clean(x.innerText))});
  });
  return out;
}
"""


@dataclass
class Field:
    jr: str
    kind: str                 # text email tel number url date textarea select combobox radio checkbox yesno file
    label: str
    name: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)
    value: str = ""

    @property
    def key(self) -> str:
        return normalize_label(self.label or self.name)


def normalize_label(text: str) -> str:
    t = re.sub(r"[✱*]", " ", (text or "").lower())
    t = re.sub(r"\(optional\)|\brequired\b", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def discover(page, root_selector: str | None = None) -> list[Field]:
    raw = page.evaluate(DISCOVER_JS, root_selector)
    fields = [Field(**{k: v for k, v in r.items() if k in Field.__dataclass_fields__}) for r in raw]
    return dedupe(fields)


def dedupe(fields: list[Field]) -> list[Field]:
    """Searchable dropdowns (react-select) expose a second input right after the real one, labelled
    'Select...' or repeating the question. Keep the first; drop the echo."""
    out: list[Field] = []
    for f in fields:
        prev = out[-1] if out else None
        if prev and f.kind in ("text", "combobox"):
            placeholder = normalize_label(f.label) in ("select", "")
            if (placeholder and prev.kind in ("combobox", "select")) or (
                    f.key and f.key == prev.key and prev.kind in ("text", "combobox", "select")):
                continue
        out.append(f)
    return out


def pick_option(options: list[str], answer: str) -> int | None:
    """Index of the option that best matches an answer, or None. Never picks at random."""
    a = normalize_label(answer)
    if not a:
        return None
    norm = [normalize_label(o) for o in options]
    for i, o in enumerate(norm):          # exact
        if o == a:
            return i
    yes, no = a in ("yes", "y", "true"), a in ("no", "n", "false")
    for i, o in enumerate(norm):          # yes / no families ("Yes, I am authorized")
        if (yes and re.match(r"^(yes|i am|i do|i have)\b", o)) or (no and re.match(r"^(no|i am not|i do not|i don t)\b", o)):
            return i
    hits = [i for i, o in enumerate(norm) if a in o or (len(o) > 2 and o in a)]
    return hits[0] if len(hits) == 1 else None


def fill(page, f: Field, value: str, root: str = "") -> bool:
    """Fill one field. Returns True if the control now holds the value."""
    sel = f'{root} [data-jr="{f.jr}"]'.strip()
    if f.kind == "file":
        page.set_input_files(sel, value)
        return True
    if f.kind in ("radio", "checkbox", "yesno"):
        idx = pick_option(f.options, value)
        if idx is None:
            return False
        page.click(f'{root} [data-jr="{f.jr}.{idx}"]'.strip(), force=True)
        return True
    if f.kind == "select":
        idx = pick_option(f.options, value)
        if idx is None:
            return False
        raw = page.eval_on_selector_all(f"{sel} option", "os => os.map(o => o.text)")
        target = next((r for r in raw if " ".join(r.split()) == f.options[idx]), None)
        if target is None:
            return False
        page.select_option(sel, label=target)
        return True
    if f.kind == "dropdown":
        return _fill_dropdown(page, sel, value)
    if f.kind == "combobox" or (f.kind == "text" and _looks_like_combobox(page, sel)):
        return _fill_combobox(page, sel, value)
    page.fill(sel, value)
    return True


def _looks_like_combobox(page, sel: str) -> bool:
    return bool(page.eval_on_selector(sel, "e => e.getAttribute('role') === 'combobox' || "
                                           "!!e.closest('[class*=select__control], [class*=combobox]')"))


OPTION_SEL = '[role="option"]:visible, [data-automation-id="promptOption"]:visible'


DECLINE_TOKEN = "__decline__"     # "pick the decline-to-self-identify option, whatever it is called"
DECLINE_RE = re.compile(r"decline|prefer not|do not wish|don.?t wish|not to (say|disclose|answer)|rather not", re.I)


def _choose_visible_option(page, value: str) -> bool:
    opts = page.locator(OPTION_SEL)
    texts = [" ".join(t.split()) for t in opts.all_inner_texts()]
    if value == DECLINE_TOKEN:
        idx = next((i for i, t in enumerate(texts) if DECLINE_RE.search(t)), None)
    else:
        idx = pick_option(texts, value)
    if idx is None:
        page.keyboard.press("Escape")
        return False
    opts.nth(idx).click()
    return True


def _fill_dropdown(page, sel: str, value: str) -> bool:
    """Button that opens a listbox (Workday 'Select One'): open it, click the matching option."""
    page.click(sel)
    page.wait_for_timeout(500)
    return _choose_visible_option(page, value)


def _fill_combobox(page, sel: str, value: str) -> bool:
    """Searchable dropdowns (react-select on Greenhouse, Workday pickers): type, then click the match."""
    page.click(sel)
    page.fill(sel, value)
    page.wait_for_timeout(600)
    if page.locator(OPTION_SEL).count() == 0:
        page.keyboard.press("Enter")          # Workday pickers search on Enter
        page.wait_for_timeout(800)
    return _choose_visible_option(page, value)
