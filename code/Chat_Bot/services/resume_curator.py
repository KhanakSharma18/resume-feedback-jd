"""
Tailors a resume to a job description.

It only REORDERS and EMPHASISES what is already in the resume. It never invents skills:
  * skills that the job asks for are moved to the front of each skills line
  * projects / experience are ordered by TF-IDF cosine similarity to the job post
  * bullets inside a project are ordered the same way
  * a short summary is generated from the matching skills and top projects
  * keywords the job wants but the resume does not have are reported, not added

The result is returned as structured data. The browser turns it into a PDF (jsPDF).
"""
import re

from .resume_analyzer import analyze_ats
from .resume_nlp import Matcher, DISPLAY, stem, raw_tokens, NOISE_STEMS

HEADINGS = {
    "education": "Education", "academics": "Education", "academic background": "Education",
    "skills": "Skills", "technical skills": "Skills", "key skills": "Skills", "core skills": "Skills",
    "projects": "Projects", "academic projects": "Projects", "personal projects": "Projects",
    "experience": "Experience", "work experience": "Experience", "professional experience": "Experience",
    "internships": "Experience", "internship": "Experience", "work history": "Experience",
    "certificates": "Certificates", "certifications": "Certificates", "certificate": "Certificates",
    "courses": "Certificates", "achievements": "Achievements", "awards": "Achievements",
    "summary": "Summary", "objective": "Summary", "profile": "Summary", "professional summary": "Summary",
    "career objective": "Summary", "positions of responsibility": "Achievements",
}

BULLET_RE = re.compile(r"^\s*[●•▪◦\-\*–]\s*(.+)$")
LABEL_RE = re.compile(r"^\s*([A-Za-z][A-Za-z &/]{1,40}?)\s*:\s*(.*)$")
TOOLS_RE = re.compile(r"^\s*(tools?|tech(nologies)?|tech stack|stack)\s*:\s*(.*)$", re.I)
DATE_END_RE = re.compile(
    r"^(.*?)\s*((?:\d{1,2}/\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|(?:19|20)\d{2})"
    r"\s*[-–—to]+\s*(?:\d{1,2}/\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}|(?:19|20)\d{2}|present|current|ongoing))\s*$",
    re.I)
DEGREE_RE = re.compile(r"(b\.?\s?tech|b\.?\s?e\b|bachelor|m\.?\s?tech|master|bca|mca|b\.?\s?sc|m\.?\s?sc|diploma|mba)", re.I)


# ----------------------------------------------------------------------
# Text clean-up (PDF extraction leaves odd spaces like "full -stack")
# ----------------------------------------------------------------------
def clean(s):
    s = s or ""
    s = re.sub(r"(\w)\s+-(?=\w)", r"\1-", s)          # full -stack -> full-stack
    s = re.sub(r"(\d)\.\s+(\d)", r"\1.\2", s)       # 9. 13 -> 9.13
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\s+([,;:.])", r"\1", s)
    s = re.sub(r"\s*·\s*", ", ", s)                 # tools separated by middle dots
    s = re.sub(r"\s+", " ", s).strip()
    # PDF text extraction often splits kerned letter pairs: "V ite", "T ailwind", "ef ficient", "CGP A"
    s = re.sub(r"\b([BD-HJ-QS-Z]) (?=[a-z]{3,})", r"\1", s)                    # single capital + lowercase word (not A, C, I, R)
    s = re.sub(r"\b(ef|dif|af|staf|stuf) (?=f[a-z])", r"\1", s)            # ef ficient -> efficient
    s = re.sub(r"\bof (?=(fice|fer|ficial))", "of", s)                      # of fice -> office
    s = s.replace("CGP A", "CGPA")
    # the PDF writer can only draw Windows-1252 characters
    return s.encode("cp1252", "replace").decode("cp1252")


def heading_of(line):
    if len(line.split()) > 4:
        return None
    key = re.sub(r"[^a-z ]", "", line.lower()).strip()
    return HEADINGS.get(key)


def split_gap(raw):
    """'Left text      right text' (3+ spaces) -> (left, right)."""
    parts = re.split(r"\s{3,}", raw.strip())
    if len(parts) >= 2:
        return clean(" ".join(parts[:-1])), clean(parts[-1])
    return clean(raw), ""


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------
def parse_resume(text):
    lines = [l.rstrip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return {"name": "", "contact": [], "sections": []}
    name = clean(lines[0])
    contact, sections, cur = [], [], None
    for ln in lines[1:]:
        h = heading_of(ln)
        if h:
            cur = {"key": h, "lines": []}
            sections.append(cur)
        elif cur is None:
            contact.append(clean(ln))
        else:
            cur["lines"].append(ln)
    return {"name": name, "contact": [c for c in contact if c], "sections": sections}


def parse_skills(lines):
    entries = []  # [label, text]
    for ln in lines:
        m = LABEL_RE.match(ln)
        if m:
            entries.append([clean(m.group(1)), m.group(2).strip()])
        elif entries:
            entries[-1][1] += " " + ln.strip()
        else:
            entries.append(["", ln.strip()])
    out = []
    for label, txt in entries:
        items = [clean(i) for i in re.split(r"\s*[,;|]\s*|\s*·\s*", txt) if clean(i)]
        out.append((label, items))
    return out


def parse_blocks(lines):
    """Projects / experience -> list of {title, date, bullets, tools}."""
    blocks, cur, last = [], None, None

    def new_block(title="", date=""):
        b = {"title": title, "date": date, "bullets": [], "tools": ""}
        blocks.append(b)
        return b

    for ln in lines:
        bm, tm = BULLET_RE.match(ln), TOOLS_RE.match(ln)
        dm = DATE_END_RE.match(ln.strip()) if not bm else None
        if bm:
            cur = cur or new_block()
            cur["bullets"].append(bm.group(1).strip())
            last = "bullet"
        elif tm:
            cur = cur or new_block()
            cur["tools"] = tm.group(3).strip()
            last = "tools"
        elif dm and len(dm.group(1).split()) <= 14:
            cur = new_block(dm.group(1).strip(), dm.group(2).strip())
            last = "title"
        elif cur is not None:      # wrapped line: glue to whatever came before
            if last == "bullet" and cur["bullets"]:
                cur["bullets"][-1] += " " + ln.strip()
            elif last == "tools":
                cur["tools"] += " " + ln.strip()
            else:
                cur["title"] = (cur["title"] + " " + ln.strip()).strip()
        else:
            cur = new_block(ln.strip())
            last = "title"
    for b in blocks:
        b["title"], b["tools"] = clean(b["title"]), clean(b["tools"])
        b["date"] = clean(b["date"])
        b["bullets"] = [clean(x) for x in b["bullets"]]
    return blocks


# ----------------------------------------------------------------------
# Curating
# ----------------------------------------------------------------------
def _role_from_jd(jd):
    first = next((l.strip() for l in (jd or "").splitlines() if l.strip()), "")
    first = re.sub(r"^(job (title|description)|position|role)\s*[:\-]\s*", "", first, flags=re.I).strip()
    if 1 <= len(first.split()) <= 7 and not first.endswith(".") and not re.match(r"^(we|about|our|the|are|join)\b", first, re.I):
        return clean(first)
    return ""


def _degree(edu_lines):
    for ln in edu_lines:
        if DEGREE_RE.search(ln):
            part = re.split(r"\s{3,}|\|", ln.strip())[0]
            part = re.sub(r"\s*(CGPA|GPA|Percentage).*$", "", part, flags=re.I)
            return clean(part)
    return ""


def _plain_text(c):
    out = [c["header"]["name"]] + c["header"]["contact"]
    for sec in c["sections"]:
        out.append(sec["title"])
        for it in sec["items"]:
            if it["type"] == "block":
                out.append((it["title"] + "  " + it["date"]).strip())
                out += ["● " + b for b in it["bullets"]]
                if it["tools"]:
                    out.append("Tools: " + it["tools"])
            elif it["type"] == "kv":
                out.append((it["label"] + ": " if it["label"] else "") + it["text"])
            elif it["type"] == "line":
                out.append(("● " if it.get("bullet") else "") + it["text"] + ("   " + it["right"] if it.get("right") else ""))
            else:
                out.append(it["text"])
    return "\n".join(out)


def curate_resume(text, job_description):
    jd = (job_description or "").strip()
    m = Matcher(text, jd)
    parsed = parse_resume(text)
    sections_in = {}
    for s in parsed["sections"]:
        sections_in.setdefault(s["key"], []).extend(s["lines"])

    notes, out_sections = [], []
    moved_skills, top_projects = [], []

    # ---- helpers ----
    def item_hits(item):
        return sum(1 for t in raw_tokens(item) if stem(t) in m.jd_term_set)

    def block_text(b):
        return " ".join([b["title"]] + b["bullets"] + [b["tools"]])

    # ---- build each section, keeping the original order ----
    for sec in parsed["sections"]:
        key = sec["key"]
        if any(o["title"] == key for o in out_sections):
            continue                                  # merged duplicate headings
        lines = sections_in[key]
        items = []

        if key == "Summary":
            continue                                  # replaced by a generated summary below

        elif key == "Skills":
            for label, skills in parse_skills(lines):
                ranked = sorted(skills, key=lambda i: -item_hits(i))  # stable: ties keep original order
                if "course" not in label.lower():
                    moved_skills += [i for i in ranked if item_hits(i) > 0]
                items.append({"type": "kv", "label": label, "text": ", ".join(ranked)})
            if moved_skills:
                notes.append("Moved skills the job asks for to the front: " + ", ".join(dict.fromkeys(moved_skills[:8])) + ".")

        elif key in ("Projects", "Experience"):
            blocks = parse_blocks(lines)
            before = [b["title"] for b in blocks]
            for b in blocks:                          # bullets: most relevant first
                b["bullets"] = sorted(b["bullets"], key=lambda x: -m.rel(x))
            if len(blocks) > 1 and any(b["title"] for b in blocks):
                blocks = sorted(blocks, key=lambda b: -m.rel(block_text(b)))
            after = [b["title"] for b in blocks]
            if key == "Projects":
                top_projects = [re.sub(r"\s*\(.*$", "", t).strip() for t in after if t][:2]
            if before != after:
                notes.append(f"Reordered {key.lower()} so the most relevant comes first: " + ", ".join(
                    re.sub(r"\s*\(.*$", "", t) for t in after if t)[:200] + ".")
            for b in blocks:
                if b["title"]:
                    items.append({"type": "block", **b})
                else:
                    items += [{"type": "line", "text": x, "bullet": True} for x in b["bullets"]]
                    if b["tools"]:
                        items.append({"type": "line", "text": "Tools: " + b["tools"]})

        elif key == "Certificates":
            rows = [split_gap(l) for l in lines]
            rows = sorted(rows, key=lambda r: -m.rel(r[0]))
            items = [{"type": "line", "text": a, "right": b} for a, b in rows]

        else:  # Education, Achievements, anything else: keep as is
            for l in lines:
                bm = BULLET_RE.match(l)
                if bm:
                    items.append({"type": "line", "text": clean(bm.group(1)), "bullet": True})
                else:
                    a, b = split_gap(l)
                    items.append({"type": "line", "text": a, "right": b})

        if items:
            out_sections.append({"title": key, "items": items})

    # ---- generated summary (only from things the resume already says) ----
    skills_sec = next((s for s in out_sections if s["title"] == "Skills"), None)
    shown = list(dict.fromkeys(moved_skills))[:4]
    if not shown and skills_sec:
        first = skills_sec["items"][0]["text"] if skills_sec["items"] else ""
        shown = [x.strip() for x in first.split(",")][:4]
    degree = _degree(sections_in.get("Education", []))
    role = _role_from_jd(jd)
    parts = []
    if shown:
        lead = f"{degree} candidate" if degree else "Candidate"
        listed = ", ".join(shown[:-1]) + (" and " if len(shown) > 1 else "") + shown[-1]
        parts.append(f"{lead} with hands-on project experience in {listed}.")
    if top_projects:
        parts.append("Projects include " + " and ".join(top_projects) + ".")
    if role:
        parts.append(f"Targeting the {role} role.")
    if parts:
        out_sections.insert(0, {"title": "Summary", "items": [{"type": "para", "text": clean(" ".join(parts))}]})
        notes.append("Added a short summary written from your own skills and projects"
                     + (" (it replaces your old summary)." if "Summary" in sections_in else "."))

    # ---- keywords the job wants that the resume does not have (not added) ----
    from .resume_nlp import match_resume_jd
    jm = match_resume_jd(text, jd)
    if jm["missing"]:
        notes.append("Not added because your resume does not mention them: " + ", ".join(jm["missing"][:8])
                     + ". Add them yourself only if you really have this experience.")

    curated = {
        "header": {"name": parsed["name"], "contact": parsed["contact"]},
        "sections": out_sections,
    }
    plain = _plain_text(curated)
    before_score = analyze_ats(text, jd)
    after_score = analyze_ats(plain, jd)
    return {
        "curated": curated,
        "notes": notes,
        "before": {"score": before_score["score"], "match": (before_score["job_match"] or {}).get("percent")},
        "after": {"score": after_score["score"], "match": (after_score["job_match"] or {}).get("percent")},
    }
