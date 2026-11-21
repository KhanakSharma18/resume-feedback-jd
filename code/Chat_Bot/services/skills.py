"""
Skill extraction.

Replaces the old hard-coded TECH_KEYWORDS list.

How it works
  1. data/skills_db.json holds ~250 skills, each with a canonical name, a category and aliases
     ("Node.js" = node, nodejs, node.js ...). Edit that file to add your own skills.
  2. extract_skills(text) finds every skill in a text (resume or job post) with a boundary-aware
     matcher, so "java" is not found inside "javascript" and "sql" is not found inside "mysql".
  3. Optional: if spaCy and its English model are installed, spacy_unknown_terms() uses Named Entity
     Recognition to spot product / tool names in a job post that are NOT in the database yet, so you
     can see what the database is missing. Nothing breaks if spaCy is not installed.

        pip install spacy
        python -m spacy download en_core_web_sm
"""
import json
import os
import re
from collections import Counter

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "skills_db.json")

_engine = None

# skill -> skills that imply it
IMPLIED = {"Version control": {"Git", "GitHub", "GitLab", "Bitbucket"}}


# ----------------------------------------------------------------------
# Matching engine (built once, on first use)
# ----------------------------------------------------------------------
def _flex(alias):
    """'machine learning' -> regex that also accepts 'machine-learning' and 'machinelearning'."""
    parts = [p for p in re.split(r"[\s\-]+", alias.strip()) if p]
    return r"[\s\-]*".join(re.escape(p) for p in parts)


def _key(alias, case_sensitive):
    k = re.sub(r"[\s\-]+", "", alias.strip())
    return k if case_sensitive else k.lower()


def _build():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            "Skills database not found at " + os.path.normpath(DB_PATH) +
            ". Copy the 'data' folder (with skills_db.json) next to app.py.")
    with open(DB_PATH, encoding="utf-8") as f:
        skills = json.load(f)["skills"]

    info = {}                      # canonical name -> category
    ci_lookup, cs_lookup = {}, {}  # normalised alias -> canonical name
    ci_alias, cs_alias, list_alias = [], [], []

    for sk in skills:
        name, cat = sk["name"], sk["category"]
        cs = bool(sk.get("case_sensitive"))
        info[name] = cat
        for alias in [name] + list(sk.get("aliases", [])):
            if alias in sk.get("list_only_aliases", []):
                continue                                   # "C" / "R" are handled by the list matcher only
            (cs_lookup if cs else ci_lookup)[_key(alias, cs)] = name
            (cs_alias if cs else ci_alias).append(alias)
        for alias in sk.get("list_only_aliases", []):
            cs_lookup["LIST:" + alias] = name
            list_alias.append(alias)

    def compile_group(aliases, flags):
        if not aliases:
            return None
        aliases = sorted(set(aliases), key=len, reverse=True)       # longest first: "react native" before "react"
        body = "|".join(_flex(a) for a in aliases)
        return re.compile(r"(?<![A-Za-z0-9.])(?:" + body + r")(?![A-Za-z0-9])", flags)

    # C / R style names: only inside lists such as "Languages: C, C++, Python"
    list_re = None
    if list_alias:
        body = "|".join(re.escape(a) for a in list_alias)
        list_re = re.compile(r"(?:^|[,;/|:\u2022\u00b7])\s*(" + body + r")(?=\s*(?:[,;/|\u2022\u00b7]|$))", re.M)

    return {
        "info": info,
        "ci_re": compile_group(ci_alias, re.I),
        "cs_re": compile_group(cs_alias, 0),
        "list_re": list_re,
        "ci_lookup": ci_lookup,
        "cs_lookup": cs_lookup,
        "all_aliases": {a.lower() for sk in skills for a in [sk["name"]] + list(sk.get("aliases", []))},
    }


def _get():
    global _engine
    if _engine is None:
        _engine = _build()
    return _engine


def reload_database():
    """Call this after editing skills_db.json if you do not want to restart the server."""
    global _engine
    _engine = None


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def extract_skills(text):
    """
    Returns [{"name": "Python", "category": "Programming languages", "count": 3}, ...]
    most-mentioned first.
    """
    eng = _get()
    text = text or ""
    # PDF extraction sometimes breaks words over lines ("Type-\nScript"): keep it simple, flatten line ends
    counts = Counter()

    if eng["ci_re"]:
        for m in eng["ci_re"].finditer(text):
            name = eng["ci_lookup"].get(_key(m.group(0), False))
            if name:
                counts[name] += 1
    if eng["cs_re"]:
        for m in eng["cs_re"].finditer(text):
            name = eng["cs_lookup"].get(_key(m.group(0), True))
            if name:
                counts[name] += 1
    if eng["list_re"]:
        for m in eng["list_re"].finditer(text):
            name = eng["cs_lookup"].get("LIST:" + m.group(1))
            if name:
                counts[name] += 1

    # a few skills are implied by others ("Git" means the person knows version control)
    for implied, triggers in IMPLIED.items():
        if implied not in counts and implied in eng["info"] and any(t in counts for t in triggers):
            counts[implied] = 1

    out = [{"name": n, "category": eng["info"][n], "count": c} for n, c in counts.items()]
    out.sort(key=lambda s: (-s["count"], s["name"].lower()))
    return out


def skill_names(text, include_soft=True):
    return {s["name"] for s in extract_skills(text) if include_soft or s["category"] != "Soft skills"}


def group_by_category(skills):
    """[{"name","category","count"}] -> {"Programming languages": ["Python", "Java"], ...}"""
    grouped = {}
    for s in skills:
        grouped.setdefault(s["category"], []).append(s["name"])
    return grouped


def is_soft(skill):
    return skill["category"] == "Soft skills"


# ----------------------------------------------------------------------
# Optional: spaCy NER to discover tools that are not in the database
# ----------------------------------------------------------------------
_nlp = None
_nlp_failed = False


def _load_spacy():
    global _nlp, _nlp_failed
    if _nlp is not None or _nlp_failed:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm", disable=["lemmatizer"])
    except Exception as e:                      # not installed / model not downloaded
        _nlp_failed = True
        print(f"[skills] spaCy NER not active ({type(e).__name__}). The skills database still works.")
    return _nlp


def spacy_available():
    return _load_spacy() is not None


_NOT_TOOLS = re.compile(r"\b(university|institute|college|school|inc|ltd|llc|pvt|corp|technologies|solutions|limited)\b", re.I)


def spacy_unknown_terms(text, limit=8):
    """
    Product / organisation-like names that spaCy finds in the text but the skills database does not know.
    Best effort: it is only used to tell you what to consider adding to skills_db.json.
    """
    nlp = _load_spacy()
    if nlp is None or not text:
        return []
    known = _get()["all_aliases"]
    seen, out = set(), []
    for ent in nlp(text[:8000]).ents:
        if ent.label_ not in ("PRODUCT", "ORG"):
            continue
        t = " ".join(ent.text.split()).strip(" .,:;()")
        low = t.lower()
        if (len(t) < 2 or len(t) > 28 or low in known or low in seen or _NOT_TOOLS.search(t)
                or not re.search(r"[A-Za-z]", t) or not t[0].isupper()):
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= limit:
            break
    return out
