"""
Checks a quiz answer. Two kinds of question:

  technical  has a model answer and key concepts (data/question_bank.json).
             score = how many key concepts you mentioned  (+ how close your answer is in MEANING to the
             model answer, when sentence-transformers is installed).
  open       project / gap / behavioural questions have no single correct answer. They are scored on a
             small rubric (did you explain the problem, your role, the result, the reasoning ...).

This is a fast, offline, repeatable check, not a human interviewer: a correct answer in very different
words can be under-scored. ai_feedback() asks your Llama model for a deeper written review on demand.
"""
import re

from . import embeddings
from .llama_test import query_model

SEM_LOW, SEM_HIGH = 0.25, 0.75          # answer-vs-model-answer cosine mapped to 0..100%
TECH_CORRECT, TECH_PARTIAL = 60, 35
OPEN_CORRECT, OPEN_PARTIAL = 65, 40


def _words(s):
    return re.findall(r"[A-Za-z0-9']+", s or "")


def _has(alts, low):
    """True if any of the 'a|b|c' alternatives appears in the (lower-case) text, allowing word endings."""
    for alt in alts.split("|"):
        alt = alt.strip().lower()
        if alt and re.search(r"(?<![a-z0-9])" + re.escape(alt) + r"\w*", low):
            return True
    return False


def _any(terms, low):
    return any(t and re.search(r"(?<![a-z0-9])" + re.escape(str(t).lower()) + r"(?![a-z0-9])", low) for t in terms or [])


def _verdict(score, ok, part):
    return "correct" if score >= ok else "partial" if score >= part else "incorrect"


# ----------------------------------------------------------------------
# Technical questions
# ----------------------------------------------------------------------
def _grade_technical(q, answer):
    low, n = answer.lower(), len(_words(answer))
    keys = q.get("keys") or []
    covered = [k for k in keys if _has(k, low)]
    missing = [k for k in keys if k not in covered]
    cov = len(covered) / len(keys) if keys else 0.0

    sem = embeddings.similarity(answer, q.get("ref", "")) if n >= 5 and q.get("ref") else None
    if sem is not None:
        sem_pct = min(1.0, max(0.0, (sem - SEM_LOW) / (SEM_HIGH - SEM_LOW)))
        score = round(100 * (0.5 * cov + 0.5 * sem_pct))
        method = "key concepts + meaning similarity"
    else:
        score = round(100 * cov)
        method = "key concepts"
    if n < 8:
        score = min(score, 30)

    good, improve = [], []
    if covered:
        good.append("You mentioned: " + ", ".join(k.split("|")[0] for k in covered[:6]) + ".")
    if n >= 30:
        good.append("Good level of detail.")
    if missing:
        improve.append("You did not mention: " + ", ".join(k.split("|")[0] for k in missing[:5]) +
                       ". Work these ideas into your answer.")
    if n < 15:
        improve.append("Your answer is very short. Explain the idea in two or three sentences.")
    verdict = _verdict(score, TECH_CORRECT, TECH_PARTIAL)
    if verdict != "correct" and not re.search(r"\b(example|for instance|e\.g|in my|i used|i built)\b", low):
        improve.append("Add a concrete example, ideally from one of your own projects.")
    return score, good, improve, verdict, method


# ----------------------------------------------------------------------
# Open questions (project / gap / behavioural)
# ----------------------------------------------------------------------
# name: (regex, praise, tip)
EL = {
    "problem":  (r"\b(problem|issue|goal|purpose|needed|aim|aimed|solve|solved|challenge|because users)\b",
                 "You explained the problem.", "Say what problem it solved."),
    "role":     (r"\bi (built|made|wrote|developed|designed|implemented|created|handled|worked|led|used|set up|integrated|added|was responsible|took|owned)\b|\bmy (role|part|task|contribution)\b",
                 "You made clear what you personally did.", "Say what YOU did, for example \"I built...\" or \"I implemented...\"."),
    "result":   (r"\d|%|\b(result|resulted|improved|reduced|increased|faster|launched|deployed|users|outcome|success|worked|learned)\b",
                 "You gave a result or outcome.", "End with the result, with a number if you have one."),
    "reason":   (r"\b(because|since|so that|therefore|trade-?off|instead of|rather than|compared|chose|choose|decided|reason)\b",
                 "You explained why, not only what.", "Explain WHY you made the choice."),
    "alt":      (r"\b(alternative|alternatives|instead of|rather than|compared (to|with)|versus|vs\.?|other options|could have|considered)\b",
                 "You compared it with alternatives.", "Name one or two alternatives you considered."),
    "tradeoff": (r"\b(downside|drawback|limitation|limit|trade-?off|cost|but|however|con|weakness)\b",
                 "You were honest about a trade-off.", "Mention one honest downside or limit."),
    "verify":   (r"\b(test|tested|testing|measure|measured|metric|metrics|benchmark|verified|validate|validated|feedback|logs?|monitor|monitored)\b",
                 "You said how you checked it worked.", "Say how you checked that it worked (tests, metrics, user feedback)."),
    "reflect":  (r"\b(learn|learned|learnt|next time|would change|improve|differently|realis|realiz|hindsight)",
                 "You reflected on what you learned or would change.", "Say what you learned or would do differently."),
    "symptom":  (r"\b(bug|error|crash|crashed|fail|failed|failing|broke|broken|issue|wrong)\b",
                 "You described the symptom.", "Start with the symptom: what went wrong."),
    "cause":    (r"\b(cause|caused|because|turned out|reason|root)\b",
                 "You identified the cause.", "Explain the root cause you found."),
    "fix":      (r"\b(fix|fixed|solved|resolved|changed|patched|solution)\b",
                 "You described the fix.", "Describe exactly how you fixed it."),
    "scale":    (r"\b(cach|index|load balanc|queue|shard|replica|paginat|cdn|horizontal|scal|bottleneck|database|rate limit)",
                 "You named concrete scaling techniques.", "Name concrete fixes: caching, indexes, load balancing, queues, pagination."),
    "monitor":  (r"\b(monitor|logging|metrics|alert|profil)",
                 "You mentioned monitoring.", "Mention how you would monitor to find the next bottleneck."),
    "honest":   (r"\b(haven'?t|have not|not yet|no direct|limited|never|only (used|read|studied)|i don'?t have|new to|not used)\b",
                 "You were honest about the gap.", "Be upfront that you have not used it in a project."),
    "plan":     (r"\b(learn|docs|documentation|tutorial|course|practice|small project|build|ramp|pair|ask|read)",
                 "You gave a plan to learn it.", "Describe how you would learn it (docs, a small project, a teammate)."),
    "timeline": (r"\b(week|weeks|days|month|months|quickly|fast|soon|first)\b",
                 "You gave a realistic timeline.", "Give a realistic timeline, such as productive within a couple of weeks."),
    "situation": (r"\b(when|during|while|once|at the time|last|in my|our project|team|college|internship|semester)\b",
                  "You set the scene with a real situation.", "Set the scene: when and where did this happen?"),
    "growth":   (r"\b(learn|grow|opportunit|challeng|interest|excited|passion|improve)",
                 "You said what you want to learn or achieve.", "Say what you want to learn or achieve in this role."),
    "conflict": (r"\b(disagree|disagreed|conflict|different (view|opinion|approach)|argu)",
                 "You described the disagreement.", "Describe the disagreement clearly."),
    "resolve":  (r"\b(listen|listened|discuss|discussed|talk|talked|compromise|agreed|decid|resolved|aligned|understand)",
                 "You showed how you resolved it.", "Explain how you resolved it (listening, discussing, compromising)."),
    "lead":     (r"\b(led|lead|guided|mentored|organised|organized|delegat|coordinat|planned)",
                 "You showed leadership.", "Show what you did to lead or guide others."),
    # context based (need the question's ctx)
    "tools":    (None, "You referred to the actual tools and project.", "Mention the project and the real tools you used."),
    "related":  (None, "You linked it to skills you already have.", "Point to related skills you already have."),
    "jobskills": (None, "You connected your answer to the job's skills.", "Connect your answer to what the job asks for."),
}

# rubric id -> [(element, points)], length is worth the remaining 20 points
RUBRICS = {
    "overview": [("problem", 20), ("role", 20), ("tools", 20), ("result", 20)],
    "choice":   [("tools", 15), ("reason", 25), ("alt", 20), ("tradeoff", 20)],
    "bullet":   [("role", 20), ("verify", 25), ("tools", 15), ("reflect", 20)],
    "hard":     [("symptom", 20), ("cause", 20), ("fix", 20), ("reflect", 20)],
    "scale":    [("scale", 40), ("monitor", 20), ("reason", 20)],
    "gap":      [("honest", 15), ("related", 25), ("plan", 25), ("timeline", 15)],
    "why":      [("jobskills", 35), ("growth", 25), ("tools", 20)],
    "learn":    [("situation", 20), ("role", 20), ("plan", 20), ("result", 20)],
    "team":     [("situation", 20), ("conflict", 20), ("resolve", 20), ("result", 20)],
    "stuck":    [("situation", 20), ("role", 20), ("plan", 20), ("result", 20)],
    "lead":     [("situation", 20), ("lead", 20), ("result", 20), ("reflect", 20)],
}


def _grade_open(q, answer):
    low, n = answer.lower(), len(_words(answer))
    ctx = q.get("ctx") or {}
    rubric = RUBRICS.get(q.get("rubric"), RUBRICS["overview"])
    score, good, improve = 0, [], []

    # length: 20 points
    if n >= 35:
        score += 20
    elif n >= 15:
        score += 10
        improve.append("Add more detail. Aim for about 40 to 100 words (three to six sentences).")
    else:
        improve.append("Your answer is too short to judge. Aim for about 40 to 100 words.")

    for name, pts in rubric:
        rx, praise, tip = EL[name]
        if name == "tools":
            hit = _any([ctx.get("project")] + list(ctx.get("tools") or []) + list(ctx.get("projects") or []), low)
        elif name == "related":
            hit = _any(ctx.get("related"), low) or bool(re.search(r"\b(similar|related|equivalent|same concept|close to)\b", low))
        elif name == "jobskills":
            hit = _any(list(ctx.get("job_skills") or []) + [ctx.get("role")], low)
        else:
            hit = re.search(rx, low) is not None
        if hit:
            score += pts
            good.append(praise)
        else:
            improve.append(tip)

    if n < 8:
        score = min(score, 25)
    return score, good, improve, _verdict(score, OPEN_CORRECT, OPEN_PARTIAL), "answer-quality rubric"


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def grade_answer(q, answer):
    answer = (answer or "").strip()
    if not answer:
        return {"verdict": "incorrect", "score": 0, "good": [], "improve": ["You did not write an answer."],
                "model_answer": q.get("ref", ""), "method": "none"}
    if q.get("kind") == "technical":
        score, good, improve, verdict, method = _grade_technical(q, answer)
    else:
        score, good, improve, verdict, method = _grade_open(q, answer)
    return {
        "verdict": verdict, "score": int(max(0, min(100, score))), "good": good, "improve": improve,
        "model_answer": q.get("ref", ""), "method": method,
        "note": ("Instant check against key concepts. Use 'Get AI feedback' for a deeper review."
                 if q.get("kind") == "technical" else
                 "There is no single right answer here, so this checks whether your answer has the parts interviewers look for."),
    }


def ai_feedback(q, answer):
    """A short written review from your Llama model, or None if it could not be reached."""
    prompt = (
        "You are a fair, honest interviewer. Review the candidate's answer.\n\n"
        f"QUESTION: {q.get('question', '')}\n\n"
        f"CANDIDATE ANSWER: {(answer or '').strip()[:2500]}\n\n"
        f"REFERENCE POINTS: {(q.get('ref') or 'none, this is an open question')[:1200]}\n\n"
        "In at most 120 words: (1) say whether the answer is correct or good, (2) say what is missing or wrong, "
        "(3) give one improved sentence the candidate could say."
    )
    reply = query_model(prompt)
    if not reply or str(reply).startswith("Model error"):
        return None
    return str(reply).strip()
