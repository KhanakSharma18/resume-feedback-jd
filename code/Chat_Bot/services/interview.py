"""
Interview quiz builder.

build_questions(resume, job_description) returns quiz-ready questions (works offline, no model needed):
    * technical : from data/question_bank.json, for skills the job asks for that you also have.
                  Each has a model answer and key concepts, so the quiz can mark it.
    * project   : built from YOUR projects (title, bullets, tools), most job-relevant first
    * gap       : skills the job asks for that are not on your resume
    * behavioural, tied to the role

Every question carries what the quiz needs to check an answer (see services/quiz.py):
    kind    "technical" | "open"
    ref     the model answer (technical) or a suggested answer structure (open)
    keys    key concepts to look for (technical)
    rubric  which rubric to score with (open)
    ctx     facts from your resume used while scoring
"""
import json
import os
import re

from . import embeddings
from .resume_analyzer import _has_metric
from .resume_curator import parse_blocks, parse_resume, _role_from_jd
from .resume_nlp import Matcher
from .skills import extract_skills

BANK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "question_bank.json")
_bank = None
NOT_TOOLS = {"CS fundamentals", "Methodologies", "Soft skills"}      # concepts, not things you "choose"
NOT_TOOL_NAMES = {"Authentication", "Responsive design", "Accessibility", "Database design", "Debugging",
                  "Code review", "Cloud computing", "Mobile development", "Version control"}
MAX_QUESTIONS = 15

TIPS = {
    "Project deep-dive": "Answer in four beats: the problem, your role, the tools and why, the result.",
    "Technical": "Define it in one line, then give an example from your own project.",
    "Gap in your resume": "Be honest. Say what you know that is close, then how you would learn it fast.",
    "Behavioural": "Use STAR: Situation, Task, Action, Result. Keep it under two minutes.",
}

ALTERNATIVES = {
    "MongoDB": "PostgreSQL or MySQL", "MySQL": "PostgreSQL or MongoDB", "PostgreSQL": "MySQL or MongoDB",
    "Firebase": "Supabase or a custom backend", "Firestore": "MongoDB or PostgreSQL",
    "React": "Vue or Angular", "Angular": "React or Vue", "Vue.js": "React or Svelte", "Next.js": "plain React with Express",
    "Node.js": "Django, Flask or Spring Boot", "Express.js": "FastAPI, Flask or NestJS", "Flask": "FastAPI or Django",
    "Django": "Flask or FastAPI", "FastAPI": "Flask or Django", "Flutter": "React Native or native Android/iOS",
    "React Native": "Flutter or native apps", "TensorFlow": "PyTorch", "PyTorch": "TensorFlow",
    "Tailwind CSS": "Bootstrap or plain CSS", "Bootstrap": "Tailwind CSS", "Redux": "Context API or Zustand",
    "Docker": "virtual machines or a managed platform", "AWS": "Azure or GCP", "GCP": "AWS or Azure",
    "Python": "Java or JavaScript", "Java": "Python or Kotlin", "JavaScript": "TypeScript", "GraphQL": "REST",
    "REST APIs": "GraphQL", "Git": "a different workflow such as trunk-based development",
}


def _load_bank():
    global _bank
    if _bank is None:
        try:
            with open(BANK_PATH, encoding="utf-8") as f:
                _bank = json.load(f).get("questions", {})
        except Exception:
            _bank = {}                                   # missing bank: the technical part is just empty
    return _bank


def _short(title):
    return re.sub(r"\s*\(.*$", "", title or "").strip(" -:|") or "this project"


def _trim(s, n=150):
    return s if len(s) <= n else s[:n - 3].rsplit(" ", 1)[0] + "..."


def _projects(text):
    """Projects (and experience entries) found in the resume as [{title, bullets, tools, kind}]."""
    out = []
    for sec in parse_resume(text)["sections"]:
        if sec["key"] in ("Projects", "Experience"):
            for b in parse_blocks(sec["lines"]):
                if b["title"] and (b["bullets"] or b["tools"]):
                    out.append({**b, "kind": sec["key"]})
    return out


def _project_text(p):
    return " ".join([p["title"]] + p["bullets"] + [p["tools"]])


def _structure(title, points):
    return title + "\n" + "\n".join("\u2022 " + p for p in points)


def build_questions(resume_text, job_description):
    jd = (job_description or "").strip()
    m = Matcher(resume_text, jd)
    jd_skills = extract_skills(jd)
    jd_tech = [s for s in jd_skills if s["category"] != "Soft skills"]
    jd_soft = [s["name"] for s in jd_skills if s["category"] == "Soft skills"]
    jd_names = {s["name"] for s in jd_tech}
    resume_sk = extract_skills(resume_text)
    resume_names = {s["name"] for s in resume_sk}
    role = _role_from_jd(jd)
    use_sem = embeddings.available()

    # ---- rank projects by relevance to the job ----
    projects = _projects(resume_text)
    for p in projects:
        txt = _project_text(p)
        found = extract_skills(txt)
        p["skills"] = {s["name"] for s in found}
        p["tools_used"] = [s["name"] for s in found if s["category"] not in NOT_TOOLS and s["name"] not in NOT_TOOL_NAMES]
        p["shared"] = [s["name"] for s in jd_tech if s["name"] in p["skills"]]
        sem = embeddings.similarity(txt, jd) if use_sem else None
        p["score"] = len(p["shared"]) + 3 * m.rel(txt) + (2 * sem if sem else 0)
    projects.sort(key=lambda p: -p["score"])
    project_names = [_short(p["title"]) for p in projects[:3]]

    groups = {"Technical": [], "Project deep-dive": [], "Gap in your resume": [], "Behavioural": []}

    def add(cat, question, why, kind, ref, rubric=None, keys=None, ctx=None):
        groups[cat].append({"category": cat, "question": question, "why": why, "tip": TIPS[cat], "kind": kind,
                            "ref": ref, "rubric": rubric, "keys": keys or [], "ctx": ctx or {}})

    # ---- project deep-dives ----
    for rank, p in enumerate(projects[:3]):
        name = _short(p["title"])
        ctx = {"project": name, "tools": p["tools_used"][:10]}
        why_rel = ("Matches the job's use of " + ", ".join(p["shared"][:3])) if p["shared"] else "One of your listed projects"
        bullets = [_trim(b, 140) for b in p["bullets"][:2]]
        tool_list = ", ".join(p["tools_used"][:5]) or "the main tools"

        add("Project deep-dive", f"Walk me through {name}. What problem did it solve and what exactly was your part?",
            why_rel, "open",
            _structure("Suggested structure for your answer:", [
                f"Problem: why {name} was needed and who it was for.",
                "Your role: " + (f"for example, \"{bullets[0]}\"" if bullets else "what you personally built."),
                f"Tools: {tool_list}, and why.",
                "Result: what worked, ideally with a number."]),
            rubric="overview", ctx=ctx)

        wanted = [t for t in p["tools_used"] if t in jd_names]       # tools the job also asks for come first
        tool = (wanted or p["tools_used"] or [None])[0]
        if tool:
            alt = ALTERNATIVES.get(tool, "other tools in the same category")
            add("Project deep-dive",
                f"In {name}, why did you choose {tool}? What alternatives did you consider and what were the trade-offs?",
                f"Interviewers test whether {tool} was a decision or a default", "open",
                _structure("Suggested structure for your answer:", [
                    f"What {tool} gave you for this project (speed, features, familiarity, cost).",
                    f"One or two alternatives, such as {alt}, and why you did not pick them.",
                    f"One honest limit or downside of {tool}.",
                    "Tie it back to a real requirement of the project."]),
                rubric="choice", ctx={**ctx, "tools": [tool] + ctx["tools"]})

        if p["bullets"]:
            best = max(p["bullets"], key=lambda b: m.rel(b))
            snippet = _trim(best)
            if _has_metric(best):
                qtext, why = f"Your resume says: \"{snippet}\" How did you measure that result?", "You quote a number, so expect to be asked how you got it"
            else:
                qtext, why = f"Your resume says: \"{snippet}\" How exactly did you do this, and what would you change now?", "Picked from your most job-relevant bullet"
            add("Project deep-dive", qtext, why, "open",
                _structure("Suggested structure for your answer:", [
                    "The problem behind that line.",
                    "Your exact steps and the tools you used.",
                    "How you checked it worked (tests, a metric, user feedback).",
                    "One thing you would improve now."]),
                rubric="bullet", ctx=ctx)

        if rank == 0:
            add("Project deep-dive", f"What was the hardest bug or design problem in {name}, and how did you solve it?",
                "Shows how you debug and think under difficulty", "open",
                _structure("Suggested structure for your answer:", [
                    "Symptom: what went wrong, in one sentence.",
                    "How you found the cause (logs, breakpoints, isolating the part).",
                    "The root cause and your fix.",
                    "What you learned or added so it does not happen again (a test, a check)."]),
                rubric="hard", ctx=ctx)
            add("Project deep-dive", f"If {name} had 100 times more users tomorrow, what would break first and how would you fix it?",
                "A common follow-up to see if you think about scale", "open",
                _structure("Suggested structure for your answer:", [
                    "Name the likely bottleneck (database, one server, slow endpoints).",
                    "Concrete fixes: caching, indexes and pagination, load balancing, background queues.",
                    "Say why each fix helps.",
                    "Mention monitoring so you can see the next bottleneck."]),
                rubric="scale", ctx=ctx)

    # ---- technical questions for skills both the job and the resume have ----
    bank = _load_bank()
    n_skills = 0
    for s in [s for s in jd_tech if s["name"] in resume_names]:
        items = bank.get(s["name"], [])
        if not items:
            continue
        take = 2 if n_skills < 3 else 1                   # the job's most-mentioned skills get two questions
        for it in items[:take]:
            add("Technical", it["q"],
                f"The job asks for {s['name']} ({s['count']} mention{'s' if s['count'] != 1 else ''}) and you list it",
                "technical", it["a"], keys=it["keys"], ctx={"skill": s["name"]})
        n_skills += 1
        if n_skills >= 7:
            break

    # ---- gaps: required by the job, absent from the resume ----
    gaps = [s for s in jd_tech if s["name"] not in resume_names]
    for s in gaps[:3]:
        related = [k["name"] for k in resume_sk if k["category"] == s["category"] and k["category"] not in NOT_TOOLS][:3]
        add("Gap in your resume",
            f"This role uses {s['name']}, which is not on your resume. Have you used it or something similar, and how would you get productive quickly?",
            f"The job mentions {s['name']} and your resume does not", "open",
            _structure("Suggested structure for your answer:", [
                f"Be honest that you have not used {s['name']} in a project.",
                "Name what you know that is close: " + (", ".join(related) if related else "a similar tool or concept") + ".",
                "Say how you would learn it: official docs, a small project, asking a teammate.",
                "Give a realistic timeline, such as productive within a week or two."]),
            rubric="gap", ctx={"gap": s["name"], "related": related})

    # ---- behavioural, tied to the role ----
    target = f"the {role} role" if role else "this role"
    add("Behavioural", f"Why are you interested in {target}, and why now?", "Almost every interview opens with it", "open",
        _structure("Suggested structure for your answer:", [
            "Link the job's main skills (" + (", ".join([s["name"] for s in jd_tech][:3]) or "its key skills") + ") to something you have built.",
            "Say what you want to learn or achieve in this role.",
            "Show you know what the team or product does.",
            "Keep it genuine and under a minute."]),
        rubric="why", ctx={"job_skills": [s["name"] for s in jd_tech][:8], "role": role, "projects": project_names})
    add("Behavioural", "Tell me about a time you had to learn a new technology quickly to finish something. What was your approach?",
        "Tests learning speed" + (", which matters because of the skills gap above" if gaps else ""), "open",
        _structure("Suggested structure (STAR):", [
            "Situation: the project and the deadline.",
            "Action: what you did to learn it (docs, tutorials, building a small prototype).",
            "Result: what you shipped and how fast.",
            "Lesson: how you would learn faster next time."]),
        rubric="learn")
    if "Teamwork" in jd_soft or "Communication" in jd_soft:
        add("Behavioural", "Describe a disagreement in a team project. How did you handle it and what was the outcome?",
            "The job post stresses teamwork or communication", "open",
            _structure("Suggested structure (STAR):", [
                "Situation: the project and what you disagreed about.",
                "Your view and the other person's view, fairly.",
                "How you resolved it: listening, discussing, testing both ideas.",
                "The outcome and what you learned."]),
            rubric="team")
    elif "Leadership" in jd_soft:
        add("Behavioural", "Tell me about a time you led or guided others on a project.", "The job post mentions leadership", "open",
            _structure("Suggested structure (STAR):", [
                "Situation: the project and your role.",
                "Action: how you organised, delegated or guided people.",
                "Result: what the team achieved.",
                "Reflection: what you would do differently."]),
            rubric="lead")
    else:
        add("Behavioural", "Tell me about a time you got stuck on a project. What did you do?",
            "Tests persistence and resourcefulness", "open",
            _structure("Suggested structure (STAR):", [
                "Situation: what you were building and where you got stuck.",
                "Action: how you tried to unblock yourself, and when you asked for help.",
                "Result: how it ended.",
                "Lesson: what you do differently now."]),
            rubric="stuck")

    # ---- mix the groups so a short quiz still covers everything (technical first: they are the most checkable) ----
    pattern = ["Technical", "Project deep-dive", "Technical", "Project deep-dive", "Behavioural", "Technical",
               "Gap in your resume", "Project deep-dive", "Technical", "Behavioural", "Gap in your resume",
               "Technical", "Project deep-dive", "Gap in your resume", "Behavioural"]
    queues = {k: list(v) for k, v in groups.items()}
    ordered = []
    while any(queues.values()) and len(ordered) < MAX_QUESTIONS:
        for cat in pattern:
            if queues[cat] and len(ordered) < MAX_QUESTIONS:
                ordered.append(queues[cat].pop(0))
    for i, q in enumerate(ordered):
        q["id"] = i + 1

    return {
        "questions": ordered,
        "projects": project_names,
        "job_skills": [s["name"] for s in jd_tech][:12],
        "gaps": [s["name"] for s in gaps][:6],
        "semantic_checking": use_sem,
    }
