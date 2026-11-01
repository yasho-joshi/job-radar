"""Decide what to put in each form field, from the user's own answers only.

Order: job-specific answers (drafted per job from the profile and reviewed by the user) ->
files -> identity -> work rights -> standard answers -> the user's regex rules -> answers the
user gave in earlier runs -> demographic policy. Anything else returns None, and the runner
pauses to ask the user. Nothing is guessed.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT
from .fields import Field, normalize_label, pick_option

ANSWERS = ROOT / "profile" / "answers.toml"
LEARNED = ROOT / "profile" / "answers_learned.json"

COUNTRIES = ["india", "united states", "usa", "us", "united kingdom", "uk", "germany", "netherlands", "ireland",
             "canada", "france", "spain", "singapore", "australia", "uae", "united arab emirates", "europe", "eu",
             "european union", "sweden", "denmark", "poland", "portugal", "switzerland", "japan"]
COUNTRY_ALIASES = {"usa": "united states", "us": "united states", "uk": "united kingdom",
                   "eu": "european union", "europe": "european union", "uae": "united arab emirates"}

EEO = re.compile(r"\b(gender|race|racial|ethnic\w*|veteran\w*|disabilit\w*|pronoun\w*|sexual orientation|"
                 r"transgender|hispanic|latino)\b")
DECLINE = re.compile(r"decline|prefer not|do not wish|don t wish|not to (say|disclose|answer)|rather not")


@dataclass
class Answer:
    value: str | None
    source: str          # where it came from, shown to the user and logged


class AnswerBank:
    def __init__(self, answers_path: Path = ANSWERS, learned_path: Path = LEARNED):
        self.learned_path = learned_path
        self.cfg = {}
        if answers_path.exists():
            with open(answers_path, "rb") as fh:
                self.cfg = tomllib.load(fh)
        self.learned: dict[str, str] = {}
        if learned_path.exists():
            self.learned = json.loads(learned_path.read_text(encoding="utf-8"))

    # -- persistence for answers the user gives during a run --------------------------
    def remember(self, label: str, value: str) -> None:
        self.learned[normalize_label(label)] = value
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        self.learned_path.write_text(json.dumps(self.learned, indent=1, ensure_ascii=False), encoding="utf-8")

    def _get(self, section: str, key: str) -> str:
        return str(self.cfg.get(section, {}).get(key, "") or "").strip()

    # -- the decision ---------------------------------------------------------------
    def resolve(self, f: Field, job_answers: dict[str, str], files: dict[str, str], job_location: str = "") -> Answer:
        self._job_location = (job_location or "").lower()
        q = f.key
        if not q:
            return Answer(None, "no question text")

        for k, v in job_answers.items():                      # 1. drafted for this job
            if normalize_label(k) == q and str(v).strip():
                return Answer(str(v), "job answers")

        if f.kind == "file":                                  # 2. files
            if re.search(r"cover", q) and files.get("cover"):
                return Answer(files["cover"], "tailored cover letter")
            if re.search(r"resume|cv|attach", q) and files.get("resume") and "autofill" not in q:
                return Answer(files["resume"], "tailored CV")
            return Answer(None, "unknown file upload")

        ident = self._identity(q)                             # 3. identity
        if ident is not None:
            return ident

        rights = self._work_rights(q)                         # 4. work authorization / sponsorship
        if rights is not None:
            return rights

        std = self._standard(q)                               # 5. standard answers
        if std is not None:
            return std

        for rule in self.cfg.get("rules", []):                # 6. user rules
            try:
                if re.search(rule.get("pattern", "$^"), q):
                    return Answer(str(rule.get("answer", "")), f"rule /{rule.get('pattern')}/")
            except re.error:
                continue

        if q in self.learned:                                 # 7. answered in an earlier run
            return Answer(self.learned[q], "your earlier answer")

        if EEO.search(q):                                     # 8. demographic questions
            if self.cfg.get("eeo", {}).get("policy", "decline") == "decline":
                idx = next((i for i, o in enumerate(f.options) if DECLINE.search(normalize_label(o))), None)
                if idx is not None:
                    return Answer(f.options[idx], "demographic: decline to self-identify")
                if f.kind == "dropdown" and not f.options:     # options appear only when opened
                    from .fields import DECLINE_TOKEN
                    return Answer(DECLINE_TOKEN, "demographic: decline to self-identify")
            if not f.required:
                return Answer("", "demographic, optional: left blank")

        if re.search(r"privacy|consent|i agree|acknowledge|terms|data processing|gdpr", q) and f.kind in ("checkbox", "radio"):
            if self.cfg.get("consent", {}).get("accept_privacy_policy") is True:
                opt = next((o for o in f.options if re.search(r"agree|accept|yes|acknowledge|consent", o, re.I)),
                           f.options[0] if f.options else "")
                return Answer(opt, "consent setting")
            return Answer(None, "consent needs your OK")

        return Answer(None, "not in your answers")

    def _identity(self, q: str) -> Answer | None:
        g = lambda k: self._get("identity", k)
        table = [
            (r"\bpreferred (first )?name\b", "first_name"),
            (r"\b(first|given) name\b", "first_name"),
            (r"\b(last|family) name\b|\bsurname\b", "last_name"),
            (r"^(full )?name$|\bfull name\b|\blegal name\b|^your name$", "full_name"),
            (r"\be ?mail\b", "email"),
            (r"\b(phone|mobile|contact number)\b", "phone"),
            (r"^country$|\bcountry of residence\b|\bcountry\b.*\bresid", "country"),
            (r"^city$|\bcurrent city\b", "city"),
            (r"\b(current )?location\b|\bwhere are you (based|located)\b", "location"),
            (r"\bcurrent (company|employer)\b|^company$|^organi[sz]ation$|\bcurrent organi[sz]ation\b", "current_company"),
            (r"\bcurrent (job )?(title|role|position|designation)\b|^job title$", "current_title"),
            (r"\blinkedin\b", "linkedin"),
            (r"\bgithub\b", "github"),
            (r"\b(portfolio|personal website|website)\b", "portfolio"),
            (r"\btotal (years of )?experience\b|\byears of (professional|total|work) experience\b", "years_experience"),
        ]
        for pat, key in table:
            if re.search(pat, q):
                if key == "full_name" and not g(key) and g("first_name"):
                    return Answer(f"{g('first_name')} {g('last_name')}".strip(), "identity")
                v = g(key)
                return Answer(v, "identity") if v else Answer(None, f"identity.{key} is empty")
        return None

    def _work_rights(self, q: str) -> Answer | None:
        authorized = [c.lower() for c in self.cfg.get("work_rights", {}).get("authorized_countries", [])]
        find = lambda text: list(dict.fromkeys(
            COUNTRY_ALIASES.get(c, c) for c in COUNTRIES if re.search(rf"\b{re.escape(c)}\b", text)))
        mentioned = find(q)
        if not mentioned and re.search(r"\b(sponsor|sponsorship|visa|authori[sz]ed|eligible|right to work)\b", q):
            mentioned = find(getattr(self, "_job_location", ""))     # e.g. "Sponsor you?" on a job in Germany
        if re.search(r"\b(sponsor|sponsorship|visa)\b", q):
            if not mentioned:
                return Answer(None, "sponsorship question without a country")
            needs = any(c not in authorized for c in mentioned)
            return Answer("Yes" if needs else "No", f"work rights ({', '.join(mentioned)})")
        if re.search(r"\b(authori[sz]ed|eligible|legally (able|permitted)|right to work|work permit)\b", q):
            if not mentioned:
                return Answer(None, "work-authorization question without a country")
            ok = all(c in authorized for c in mentioned)
            return Answer("Yes" if ok else "No", f"work rights ({', '.join(mentioned)})")
        return None

    def _standard(self, q: str) -> Answer | None:
        table = [
            (r"\bnotice period\b|\bhow soon can you (join|start)\b", "notice_period"),
            (r"\b(expected|desired|target)\b.*\b(salary|ctc|compensation|ote|pay)\b|\bsalary expectation", "expected_salary"),
            (r"\bcurrent\b.*\b(salary|ctc|compensation)\b", "current_salary"),
            (r"\b(relocat)\w*", "willing_to_relocate"),
            (r"\b(earliest )?start date\b|\bwhen can you start\b|\bavailability to start\b", "earliest_start"),
            (r"\bhow did you (hear|find|learn)\b|\bwhere did you (hear|find)\b|\breferral source\b", "hear_about"),
        ]
        for pat, key in table:
            if re.search(pat, q):
                v = self._get("standard", key)
                return Answer(v, "standard") if v else Answer(None, f"standard.{key} is empty")
        return None


def choose_for(f: Field, ans: Answer) -> str | None:
    """For option-type fields, map the answer onto an actual option; None if it doesn't fit."""
    if ans.value is None:
        return None
    if f.kind in ("dropdown", "combobox") and not f.options:
        return ans.value          # options only appear once the list is opened; fill() matches them then
    if f.kind in ("radio", "checkbox", "yesno", "select") and f.options:
        idx = pick_option(f.options, ans.value)
        return f.options[idx] if idx is not None else None
    return ans.value
