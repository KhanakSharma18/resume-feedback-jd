"""
Resume analysis helpers.

- analyze_ats(): fast, rule-based checks (no model needed). Returns an ATS score,
  a per-check breakdown, a list of weaknesses and a list of improvements.
- ai_review():   asks your Llama model for a written review (slower, may time out).

The score is an ESTIMATE based on common ATS rules. Real ATS software differs.
"""
import re

from .llama_test import query_model
from .resume_nlp import match_resume_jd
from .skills import extract_skills, group_by_category

# ----------------------------------------------------------------------
# Word lists
# ----------------------------------------------------------------------
STRONG_VERBS = {
    "developed", "built", "implemented", "designed", "deployed", "created",
    "engineered", "optimized", "optimised", "led", "managed", "automated",
    "architected", "integrated", "launched", "improved", "reduced", "increased",
    "analyzed", "analysed", "delivered", "configured", "migrated", "tested",
    "established", "organized", "organised", "coordinated", "achieved",
    "collaborated", "researched", "streamlined", "maintained", "wrote",
}

SECTION_PATTERNS = {
    "education": r"\beducation\b",
    "skills": r"\bskills?\b",
    "projects": r"\bprojects?\b",
    "experience": r"\b(experience|internships?|work history)\b",
    "certifications": r"\b(certificat\w+|courses?|achievements?)\b",
    "summary": r"\b(summary|objective|profile)\b",
}

STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "that",
    "this", "have", "has", "from", "such", "their", "they", "who", "all", "can",
    "able", "must", "should", "etc", "work", "working", "years", "year",
    "experience", "ability", "strong", "good", "team", "role", "job", "skills",
    "knowledge", "including", "using", "use", "new", "within", "across", "into",
    "about", "more", "other", "also", "well", "need", "required", "preferred",
    "developer", "developers", "engineer", "engineers", "candidate", "looking",
    "responsibilities", "requirements", "company", "position", "join", "we",
}

BULLET_RE = re.compile(r"^\s*[●•▪◦\-\*–]\s*(.+)$")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{4}|\d{1,2}/\d{1,2}/\d{4}|(19|20)\d{2})\b")


def _bullets(text):
    out = []
    for line in text.splitlines():
        m = BULLET_RE.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def _clean_numbers(s):
    """Remove dates/years so they are not counted as 'impact numbers'."""
    s = re.sub(r"\b\d{1,2}/\d{4}\b", " ", s)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    return s


def _has_metric(bullet):
    s = _clean_numbers(bullet)
    if re.search(r"\d+(\.\d+)?\s*(%|\+|x\b|k\b|ms\b|users?|requests?|customers?|hours?|seconds?|orders?|clients?)", s, re.I):
        return True
    return re.search(r"\b\d{2,}\b", s) is not None


# ----------------------------------------------------------------------
# ATS analysis
# ----------------------------------------------------------------------
def analyze_ats(text, job_description=""):
    text = text or ""
    low = text.lower()
    words = re.findall(r"[A-Za-z][A-Za-z+#.\-]*", text)
    word_count = len(words)
    bullets = _bullets(text)

    breakdown = []

    def add(name, score, maxs, note, tip):
        breakdown.append({
            "name": name, "score": int(score), "max": maxs,
            "note": note, "tip": tip,
        })

    # 1. Contact details (10)
    has_email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text) is not None
    has_phone = re.search(r"(\+?\d[\d\s\-()]{8,}\d)", text) is not None
    has_link = ("linkedin.com" in low) or ("github.com" in low)
    s = 4 * has_email + 3 * has_phone + 3 * has_link
    missing = [n for n, ok in (("email", has_email), ("phone number", has_phone), ("LinkedIn/GitHub link", has_link)) if not ok]
    add("Contact details", s, 10,
        "All contact details found." if not missing else "Missing: " + ", ".join(missing) + ".",
        "Put email, phone and a LinkedIn or GitHub link at the top." if missing else "")

    # 2. Standard sections (20)
    found = {k: re.search(p, low) is not None for k, p in SECTION_PATTERNS.items()}
    s = 6 * found["education"] + 6 * found["skills"] + 6 * (found["projects"] or found["experience"]) \
        + 2 * (found["certifications"] or found["summary"])
    missing = []
    if not found["education"]: missing.append("Education")
    if not found["skills"]: missing.append("Skills")
    if not (found["projects"] or found["experience"]): missing.append("Projects or Experience")
    add("Standard sections", s, 20,
        "Core sections found." if not missing else "Missing sections: " + ", ".join(missing) + ".",
        "Use plain headings such as Education, Skills, Projects, Experience so ATS can read them." if missing else "")
    if not found["summary"]:
        breakdown[-1]["tip"] = (breakdown[-1]["tip"] + " " if breakdown[-1]["tip"] else "") + \
            "Consider adding a 2-line summary at the top."

    # 3. Skills / keyword coverage (15)
    # skills now come from the skills database (data/skills_db.json), not a fixed keyword list
    found_skills = [k for k in extract_skills(text) if k["category"] != "Soft skills"]
    s = min(15, round(len(found_skills) * 15 / 12))
    n_cat = len({k["category"] for k in found_skills})
    add("Skills and keywords", s, 15,
        f"{len(found_skills)} skills found across {n_cat} categor{'y' if n_cat == 1 else 'ies'}.",
        "List more tools, languages and frameworks that match the jobs you apply to." if s < 15 else "")

    # 4. Action verbs (15)
    if bullets:
        strong = sum(1 for b in bullets if b.split()[0].lower().strip(".,:;") in STRONG_VERBS)
        ratio = strong / len(bullets)
        s = round(15 * min(1.0, ratio / 0.7))
        note = f"{strong} of {len(bullets)} bullet points start with a strong action verb."
    else:
        s, note = 4, "No bullet points detected."
    add("Action verbs", s, 15, note,
        "Start every bullet with a verb like Built, Developed, Optimized, Led." if s < 15 else "")

    # 5. Quantified impact (15)
    metric = sum(1 for b in bullets if _has_metric(b))
    s = min(15, metric * 5)
    add("Measurable results", s, 15,
        f"{metric} bullet point(s) include numbers or results.",
        "Add numbers: users, % improvement, speed, size of data, team size. Aim for 3 or more bullets." if s < 15 else "")

    # 6. Length (10)
    if 300 <= word_count <= 700: s = 10
    elif 200 <= word_count < 300 or 700 < word_count <= 900: s = 7
    elif 100 <= word_count < 200: s = 4
    else: s = 2
    add("Resume length", s, 10, f"About {word_count} words.",
        "Aim for 300 to 700 words (one page for students)." if s < 10 else "")

    # 7. Dates (5)
    dates = len(DATE_RE.findall(text))
    s = 5 if dates >= 3 else 3 if dates >= 1 else 0
    add("Dates", s, 5, f"{dates} date(s) found.",
        "Add dates (MM/YYYY) to projects, education and certificates." if s < 5 else "")

    # 8. Detail in projects / experience (10)
    s = min(10, round(len(bullets) * 10 / 8))
    add("Detail in projects/experience", s, 10, f"{len(bullets)} bullet points found.",
        "Describe each project in 2 to 4 bullets: what you built, which tools, and the result." if s < 10 else "")

    base = sum(b["score"] for b in breakdown)

    # Job description match (optional): TF-IDF cosine + skills coverage + semantic (embedding) similarity
    job_match = None
    final = base
    jd = (job_description or "").strip()
    if len(jd) >= 15:
        job_match = match_resume_jd(text, jd)
        # the 8 resume rules above stay intact; the job match is blended in on top
        final = round(0.6 * base + 0.4 * job_match["percent"])

    if final >= 80: label = "Strong"
    elif final >= 60: label = "Good, but needs work"
    else: label = "Needs work"

    weaknesses = [f"{b['name']}: {b['note']}" for b in breakdown if b["score"] < b["max"]]
    improvements = [b["tip"] for b in breakdown if b["score"] < b["max"] and b["tip"]]
    if job_match:
        if job_match["percent"] < 60:
            weaknesses.append(f"Low match with the job description ({job_match['percent']}%).")
        if job_match["missing"]:
            weaknesses.append("Important job keywords not found: " + ", ".join(job_match["missing"][:8]) + ".")
        for sent in job_match["uncovered"][:2]:
            weaknesses.append("Not covered by your resume: " + sent)
        improvements.extend(job_match["recommendations"])

    return {
        "score": int(final),
        "base_score": int(base),
        "label": label,
        "breakdown": breakdown,
        "job_match": job_match,
        "skills": {"total": len(found_skills), "by_category": group_by_category(found_skills)},
        "weaknesses": weaknesses,
        "improvements": improvements,
    }


# ----------------------------------------------------------------------
# AI review (uses your Llama model)
# ----------------------------------------------------------------------
PROMPTS = {
    "weaknesses": (
        "You are a strict but fair resume reviewer. Read the resume below and list its 5 biggest "
        "weaknesses as short bullet points. Be specific to this resume. Do not rewrite the resume."
    ),
    "improve": (
        "You are a career coach. Read the resume below and give 5 specific, actionable improvements "
        "the candidate should make. Be specific to this resume. Do not rewrite the whole resume."
    ),
}


def ai_review(text, kind, job_description=""):
    """Returns the model's text, or None if the model could not be reached."""
    prompt = PROMPTS.get(kind)
    if not prompt:
        return None
    jd = (job_description or "").strip()
    extra = f"\n\nJOB DESCRIPTION (focus on how well the resume fits this job):\n{jd[:3000]}" if len(jd) >= 15 else ""
    reply = query_model(f"{prompt}\n\nRESUME:\n{(text or '')[:6000]}{extra}")
    if not reply or str(reply).startswith("Model error"):
        return None
    return reply
