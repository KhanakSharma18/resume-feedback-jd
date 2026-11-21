"""
Small NLP toolkit for matching a resume against a job description.
Pure Python, so there is nothing extra to install.

Pipeline
  1. Normalise text (lower-case, merge variants: "ReactJS" / "React.js" -> react, "C++" -> cpp ...)
  2. Tokenise, remove stop words, light stemming ("building" -> "build", "APIs" -> "api")
  3. Build unigrams + bigrams
  4. TF-IDF   : weight = (1 + ln(tf)) * idf, idf learned from the sentences of the resume and the job post
  5. Cosine similarity between the resume vector and the job-description vector
  6. Weighted keyword coverage: how much of the job's most important terms the resume contains
  7. Requirement check: job sentences that no resume line is similar to
  8. NEW - skills database (services/skills.py) finds the real skills in both texts
  9. NEW - sentence embeddings (services/embeddings.py) compare the MEANING of job requirements and resume lines
"""
import math
import re
from collections import Counter

from . import embeddings
from .skills import extract_skills, spacy_unknown_terms

# ----------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------
STOP = set("""
a an the and or of to in on for with by at from as is are was were be been being this that these those
it its you your our we they their them he she his her i will would can could should may might must shall
do does did done have has had having not no nor so than then too very just also into over under about
above below between through during before after up down out off again further once here there when
where why how all any both each few more most other some such only own same
""".split())

# Words that fill job posts but say nothing about skills (kept out of the keyword list)
NOISE = set("""
experience experienced work working works year years ability able skill skills strong good great
team teams role roles job jobs looking candidate candidates required require requires requirement requirements
preferred prefer including include includes knowledge using use used new etc plus bonus excellent
understanding familiarity proficiency proficient degree company opportunity opportunities join position
across within highly responsibilities responsibility responsible duties qualification qualifications
ideal passion passionate fast paced environment seeking hire hiring apply intern internship fresher
developer developers engineer engineers support help build building ensure make making like
write writing integrate integrating integration scientist analyst manager related based various strong
""".split())

# Multi-word / special forms merged into one token before tokenising
PHRASES = [
    (r"node\.?\s?js", "nodejs"), (r"react\.?\s?js", "react"), (r"express\.?\s?js", "expressjs"),
    (r"next\.?\s?js", "nextjs"), (r"vue\.?\s?js", "vuejs"), (r"angular\.?\s?js", "angular"),
    (r"c\+\+", "cpp"), (r"c#", "csharp"), (r"ci\s*/\s*cd", "cicd"),
    (r"machine[- ]learning", "machinelearning"), (r"deep[- ]learning", "deeplearning"),
    (r"data[- ]structures?", "datastructures"), (r"object[- ]oriented( programming)?", "oop"),
    (r"rest(ful)?[- ]?apis?", "restapi"), (r"amazon web services", "aws"),
    (r"google cloud( platform)?", "gcp"), (r"postgres(ql)?", "postgresql"),
    (r"mongo\s?db", "mongodb"), (r"my\s?sql", "mysql"), (r"java\s?script", "javascript"),
    (r"type\s?script", "typescript"), (r"tailwind(\s?css)?", "tailwind"),
    (r"problem[- ]solving", "problemsolving"), (r"version control", "versioncontrol"),
    (r"full[- ]stack", "fullstack"), (r"front[- ]end", "frontend"), (r"back[- ]end", "backend"),
    (r"natural language processing", "nlp"), (r"large language models?", "llm"),
    (r"web[- ]?sockets?", "websocket"), (r"unit tests?|unit testing", "unittest"),
]
SYN = {
    "js": "javascript", "ts": "typescript", "node": "nodejs", "express": "expressjs",
    "k8s": "kubernetes", "golang": "go", "ml": "machinelearning", "dl": "deeplearning",
    "oops": "oop", "apis": "api", "reactjs": "react",
}

# Nice names for tokens we show to the user (also marks tokens as "technical")
DISPLAY = {
    "nodejs": "Node.js", "expressjs": "Express.js", "nextjs": "Next.js", "vuejs": "Vue.js",
    "react": "React", "angular": "Angular", "cpp": "C++", "csharp": "C#", "cicd": "CI/CD",
    "javascript": "JavaScript", "typescript": "TypeScript", "mongodb": "MongoDB", "mysql": "MySQL",
    "postgresql": "PostgreSQL", "aws": "AWS", "gcp": "GCP", "sql": "SQL", "html": "HTML", "css": "CSS",
    "api": "API", "restapi": "REST APIs", "oop": "OOP", "machinelearning": "machine learning",
    "deeplearning": "deep learning", "datastructures": "data structures", "docker": "Docker",
    "kubernetes": "Kubernetes", "git": "Git", "github": "GitHub", "python": "Python", "java": "Java",
    "firebase": "Firebase", "tailwind": "Tailwind CSS", "fullstack": "full-stack", "frontend": "frontend",
    "backend": "backend", "nlp": "NLP", "llm": "LLM", "problemsolving": "problem solving",
    "versioncontrol": "version control", "flutter": "Flutter", "redux": "Redux", "django": "Django",
    "flask": "Flask", "spring": "Spring", "linux": "Linux", "azure": "Azure", "tensorflow": "TensorFlow",
    "pytorch": "PyTorch", "pandas": "pandas", "numpy": "NumPy", "agile": "Agile", "jenkins": "Jenkins",
    "graphql": "GraphQL", "redis": "Redis", "kafka": "Kafka", "websocket": "WebSockets",
    "unittest": "unit testing", "jest": "Jest", "figma": "Figma", "bootstrap": "Bootstrap",
    "jwt": "JWT", "ui": "UI", "ux": "UX", "go": "Go", "rust": "Rust", "php": "PHP", "scala": "Scala",
    "firestore": "Firestore", "vite": "Vite", "webpack": "Webpack", "terraform": "Terraform",
}
TECH = set(DISPLAY)


# ----------------------------------------------------------------------
# Text -> tokens
# ----------------------------------------------------------------------
def _normalise(text):
    low = (text or "").lower()
    for pat, rep in PHRASES:
        low = re.sub(r"(?<![a-z0-9])(?:" + pat + r")(?![a-z0-9])", " " + rep + " ", low)
    return low


def stem(tok):
    """Very light stemmer. Good enough to treat 'developed/developing/develops' alike."""
    if tok in DISPLAY or len(tok) <= 4:
        return tok
    if tok.endswith("ies") and len(tok) > 5:
        return tok[:-3] + "y"
    if tok.endswith("ss"):
        pass
    elif tok.endswith("s"):
        tok = tok[:-1]
    if tok.endswith("ing") and len(tok) > 5:
        tok = tok[:-3]
    elif tok.endswith("ed") and len(tok) > 4:
        tok = tok[:-2]
    return tok


def raw_tokens(text):
    """Canonical tokens (before stemming), stop words removed."""
    out = []
    for t in re.findall(r"[a-z][a-z0-9]*", _normalise(text)):
        t = SYN.get(t, t)
        if len(t) > 1 and t not in STOP:
            out.append(t)
    return out


def stems(text):
    return [stem(t) for t in raw_tokens(text)]


def ngrams(st):
    return st + [a + " " + b for a, b in zip(st, st[1:])]


def chunks(text):
    """Sentences / lines, used as 'documents' for IDF and for the requirement check."""
    parts = re.split(r"[\n.;!?●•▪]+", text or "")
    return [p.strip() for p in parts if len(stems(p)) >= 3]


NOISE_STEMS = {stem(w) for w in NOISE}


# ----------------------------------------------------------------------
# TF-IDF + cosine
# ----------------------------------------------------------------------
class TfIdf:
    def __init__(self, corpus):
        n = len(corpus)
        df = Counter()
        for doc in corpus:
            df.update(set(doc))
        self.idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self.default = math.log(n + 1) + 1.0

    def vec(self, toks):
        tf = Counter(toks)
        return {t: (1.0 + math.log(c)) * self.idf.get(t, self.default) for t, c in tf.items()}


def cosine(a, b):
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class Matcher:
    """Fits TF-IDF on the resume + job description and scores any text against the job."""

    def __init__(self, resume, jd):
        self.resume, self.jd = resume or "", jd or ""
        self.r_stems, self.j_stems = stems(self.resume), stems(self.jd)
        corpus = [ngrams(stems(c)) for c in chunks(self.resume) + chunks(self.jd)]
        if len(corpus) < 2:
            corpus = [ngrams(self.r_stems), ngrams(self.j_stems)]
        self.tf = TfIdf(corpus)
        self.jv = self.tf.vec(ngrams(self.j_stems))
        self.jd_term_set = {s for s in self.j_stems if s not in NOISE_STEMS and len(s) > 2}

    def rel(self, text):
        """Cosine similarity of any text with the job description (0..1)."""
        return cosine(self.tf.vec(ngrams(stems(text))), self.jv)


# ----------------------------------------------------------------------
# Resume vs job description
# ----------------------------------------------------------------------
COSINE_FULL_MARKS = 0.15   # resume vs job post cosines are small (short texts, different styles): 0.15 is already a strong match


def _surface_map(jd):
    """stem -> a readable form of the word as it appears in the job post."""
    seen = {}
    for t in raw_tokens(jd):
        seen.setdefault(stem(t), Counter())[t] += 1
    return {s: DISPLAY.get(c.most_common(1)[0][0], c.most_common(1)[0][0]) for s, c in seen.items()}


def _norm_key(x):
    return re.sub(r"[^a-z0-9+#]", "", x.lower())


def match_resume_jd(resume, jd, top_n=25):
    m = Matcher(resume, jd)
    cos = cosine(m.tf.vec(ngrams(m.r_stems)), m.jv)
    sim_pct = round(100 * min(1.0, cos / COSINE_FULL_MARKS))

    # --- weighted keyword extraction from the job post (TF-IDF weights) ---
    jc = Counter(m.j_stems)
    weights = {}
    for s, c in jc.items():
        if s in NOISE_STEMS or len(s) < 3 or s.isdigit():
            continue
        w = (1.0 + math.log(c)) * m.tf.idf.get(s, m.tf.default)
        if s in TECH:
            w *= 1.6
        weights[s] = w
    top = sorted(weights, key=lambda s: -weights[s])[:top_n]

    r_set = set(m.r_stems)
    r_count = Counter(m.r_stems)
    disp = _surface_map(jd)
    matched = [s for s in top if s in r_set]
    missing = [s for s in top if s not in r_set]
    total_w = sum(weights[s] for s in top) or 1.0
    token_cov = round(100 * sum(weights[s] for s in matched) / total_w)

    # --- skills from the skills database (replaces guessing from raw words) ---
    jd_skills = [s for s in extract_skills(jd) if s["category"] != "Soft skills"]
    rs_skills = [s for s in extract_skills(resume) if s["category"] != "Soft skills"]
    rs_names = {s["name"] for s in rs_skills}
    jd_names = {s["name"] for s in jd_skills}
    sk_matched = [s for s in jd_skills if s["name"] in rs_names]
    sk_missing = [s for s in jd_skills if s["name"] not in rs_names]
    sk_extra = [s["name"] for s in rs_skills if s["name"] not in jd_names][:10]
    if jd_skills:
        sw = lambda s: 1.0 + math.log(s["count"])
        skill_cov = round(100 * sum(sw(s) for s in sk_matched) / sum(sw(s) for s in jd_skills))
        coverage = round(0.5 * token_cov + 0.5 * skill_cov)
    else:                                   # job post names no known skill: fall back to words only
        skill_cov, coverage = None, token_cov

    # --- semantic similarity (sentence embeddings); None if the model is not installed ---
    sem = embeddings.semantic_match(resume, jd)
    if sem:
        match = round(0.40 * coverage + 0.20 * sim_pct + 0.40 * sem["percent"])
    else:
        match = round(0.6 * coverage + 0.4 * sim_pct)

    # --- requirement sentences that nothing in the resume resembles ---
    r_vecs = [m.tf.vec(ngrams(stems(c))) for c in chunks(resume)]
    cands = []
    for sent in chunks(jd):
        st = stems(sent)
        important = sum(weights.get(s, 0.0) for s in set(st))
        if important <= 0:
            continue
        sv = m.tf.vec(ngrams(st))
        best = max((cosine(sv, rv) for rv in r_vecs), default=0.0)
        cands.append((important, " ".join(sent.split()), best))
    sem_hits = None
    if sem and cands:
        sem_hits = embeddings.best_matches([c[1] for c in cands], embeddings.semantic_chunks(resume) or [resume])
    uncovered = []
    for i, (imp, sent, best) in enumerate(cands):
        if sem_hits is not None:
            # needs BOTH views to agree it is not covered (word overlap AND meaning)
            if best < 0.15 and sem_hits[i][0] < embeddings.SEM_COVERED:
                uncovered.append((imp, sent))
        elif best < 0.15:
            uncovered.append((imp, sent))
    uncovered = [s[:170] for _, s in sorted(uncovered, key=lambda x: -x[0])[:4]]

    # --- recommendations ---
    recs = []
    said = set()
    for sk in sk_missing[:6]:
        n = sk["count"]
        said.add(_norm_key(sk["name"]))
        recs.append(f"The job mentions \"{sk['name']}\" {n} time{'s' if n != 1 else ''} and your resume never does. "
                    f"If you have used it, add it to your Skills section and to a project bullet.")
    for s in missing:
        if len(recs) >= 6:
            break
        if _norm_key(disp.get(s, s)) in said or _norm_key(disp.get(s, s)) in {_norm_key(n) for n in rs_names}:
            continue
        n = jc[s]
        recs.append(f"The job mentions \"{disp.get(s, s)}\" {n} time{'s' if n != 1 else ''} and your resume never does. "
                    f"If you have used it, add it to your Skills section and to a project bullet.")
    for s in [s for s in matched if r_count[s] == 1][:3]:
        recs.append(f"\"{disp.get(s, s)}\" appears only once in your resume. Show it in action in a project bullet.")
    for sent in uncovered[:3]:
        recs.append(f"The job asks: \"{sent}\" Nothing in your resume covers this yet. "
                    f"Add a bullet that shows it, if it is true for you.")
    if sim_pct < 40 and not (sem and sem["percent"] >= 60):
        recs.append("Your resume's wording is quite different from the job post. Reuse the post's own terms "
                    "(where they are accurate) in your summary, skills and project bullets.")

    # --- readable matched / missing lists: database skills first, then other important words ---
    def merge(skill_list, token_list):
        out, seen = [], set()
        for name in [s["name"] for s in skill_list] + [disp.get(t, t) for t in token_list]:
            k = _norm_key(name)
            if k and k not in seen:
                seen.add(k)
                out.append(name)
        return out

    known_missing = {_norm_key(n) for n in rs_names}
    tok_missing = [t for t in missing if _norm_key(disp.get(t, t)) not in known_missing]
    tok_matched = [t for t in matched if _norm_key(disp.get(t, t)) not in jd_names]

    unknown = [t for t in spacy_unknown_terms(jd)
               if _norm_key(t) not in {_norm_key(x) for x in (resume or "").split()}][:6]

    return {
        "percent": int(match),
        "similarity": int(sim_pct),
        "coverage": int(coverage),
        "cosine": round(cos, 3),
        "semantic": sem["percent"] if sem else None,      # None = sentence-transformers not installed
        "evidence": sem["evidence"] if sem else [],
        "skills": {
            "matched": [s["name"] for s in sk_matched],
            "missing": [s["name"] for s in sk_missing],
            "extra": sk_extra,
            "coverage": skill_cov,
            "unknown_in_job": unknown,                     # spaCy NER guesses, only if spaCy is installed
        },
        "matched": merge(sk_matched, tok_matched)[:15],
        "missing": merge(sk_missing, tok_missing)[:12],
        "uncovered": uncovered,
        "recommendations": recs,
    }
