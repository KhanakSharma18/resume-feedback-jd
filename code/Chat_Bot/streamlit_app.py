"""
Streamlit front end for "Resume feedback against a job description".
Reuses the same services/ code as the Flask app (app.py).
The Llama 3.1 8B model is called through the Groq API (secret GROQ_API_KEY).
"""
import os
import sys

import streamlit as st
from PyPDF2 import PdfReader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# secrets -> environment variables (set them in Streamlit Cloud: App settings -> Secrets)
try:
    for _k in ("GROQ_API_KEY", "GROQ_MODEL", "LLAMA_API_URL"):
        if _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass
# the heavy semantic model is off on the free host; the keyword + TF-IDF match still works
os.environ.setdefault("RESUME_EMBEDDINGS", "off")

from services.llama_test import query_model                      # noqa: E402
from services.resume_analyzer import analyze_ats, ai_review      # noqa: E402
from services.resume_curator import curate_resume, _plain_text   # noqa: E402
from services.interview import build_questions                   # noqa: E402
from services.quiz import grade_answer, ai_feedback              # noqa: E402

st.set_page_config(page_title="Resume Feedback vs Job Description", page_icon="📄", layout="wide")
st.title("📄 Resume feedback against a job description")
st.caption("SCSE4041 Mini Project, team PE-B49-22. Llama 3.1 8B Instruct via Groq + rule-based checks.")
if st.sidebar.button("Test model"):
    st.sidebar.write("Key loaded:", bool(os.environ.get("GROQ_API_KEY")))
    st.sidebar.write(query_model("Say hello in five words.", concise=False))


def read_pdf(file):
    try:
        reader = PdfReader(file)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        st.error(f"Could not read this PDF: {e}")
        return ""


# ---------------- inputs ----------------
left, right = st.columns(2)
with left:
    up = st.file_uploader("1. Upload your resume (PDF only)", type=["pdf"])
with right:
    jd = st.text_area("2. Paste the job description (optional for the ATS score, needed for tailoring and the quiz)",
                      height=160)

resume_text = ""
if up is not None:
    resume_text = read_pdf(up)
    if not resume_text.strip():
        st.error("No readable text was found in this PDF. Scanned or image-only PDFs have no text to read. "
                 "Please upload a text-based PDF.")
        resume_text = ""
    else:
        st.success(f"Resume read: {len(resume_text)} characters.")
else:
    st.info("Upload a resume PDF to begin. You can try test-data/sample_resume_fake.pdf from the repository.")

if not resume_text:
    st.stop()

tab_ats, tab_ai, tab_chat, tab_cur, tab_quiz = st.tabs(
    ["ATS score and job match", "AI review (Llama)", "Ask about the PDF", "Tailored resume", "Interview quiz"])

# ---------------- ATS score + job match ----------------
with tab_ats:
    if st.button("Analyse resume", type="primary"):
        try:
            st.session_state["ats"] = analyze_ats(resume_text, jd)
        except Exception as e:
            st.error(f"Could not analyse the resume: {e}")
    res = st.session_state.get("ats")
    if res:
        c1, c2 = st.columns(2)
        c1.metric("ATS score (estimate)", f"{res['score']}/100", res["label"])
        jm = res.get("job_match")
        if jm:
            c2.metric("Job match", f"{jm['percent']}%")
        else:
            c2.info("No job description (15+ characters) given, so there is no job match section.")
        st.subheader("Score breakdown")
        st.table([{"Check": b["name"], "Score": f"{b['score']}/{b['max']}", "Note": b["note"], "Tip": b["tip"]}
                  for b in res["breakdown"]])
        if jm:
            a, b = st.columns(2)
            a.subheader("Matched skills / keywords")
            a.write(", ".join(jm["matched"]) or "none")
            b.subheader("Missing from your resume")
            b.write(", ".join(jm["missing"]) or "none")
        st.subheader("Skills found")
        for cat, names in res["skills"]["by_category"].items():
            st.write(f"**{cat}:** " + ", ".join(map(str, names)))
        w, i = st.columns(2)
        w.subheader("Weaknesses")
        for x in res["weaknesses"]:
            w.write("- " + x)
        i.subheader("Improvements")
        for x in res["improvements"]:
            i.write("- " + x)

# ---------------- AI review ----------------
with tab_ai:
    st.write("Written feedback from Llama 3.1 8B (prompts P1 and P2).")
    c1, c2 = st.columns(2)
    for col, kind, label in ((c1, "weaknesses", "Your 5 biggest weaknesses (P1)"),
                             (c2, "improve", "5 improvements (P2)")):
        with col:
            if st.button(label, key=f"ai_{kind}"):
                with st.spinner("Asking the model..."):
                    out = ai_review(resume_text, kind, jd)
                st.session_state[f"ai_{kind}_out"] = out or "MODEL_ERROR"
            out = st.session_state.get(f"ai_{kind}_out")
            if out == "MODEL_ERROR":
                st.error("The model could not be reached. The rule-based results in the first tab still work.")
            elif out:
                st.markdown(out)

# ---------------- chat about the PDF ----------------
with tab_chat:
    st.write("Ask a question about your uploaded resume (prompt P3).")
    q = st.text_input("Your question", key="chat_q")
    if st.button("Ask") and q.strip():
        prompt = ("Based on the following PDF content, answer the user's question.\n"
                  f"PDF Content:\n{resume_text}\n\nUser Question: {q}")
        with st.spinner("Asking the model..."):
            reply = query_model(prompt)
        if str(reply).startswith("Model error"):
            st.error("The model could not be reached. Try again in a minute.")
        else:
            st.markdown(reply)

# ---------------- tailored resume ----------------
with tab_cur:
    if len(jd.strip()) < 15:
        st.info("Paste the job description first.")
    elif st.button("Tailor my resume to this job"):
        try:
            st.session_state["cur"] = curate_resume(resume_text, jd)
        except Exception as e:
            st.error(f"Could not tailor the resume: {e}")
    cur = st.session_state.get("cur")
    if cur and len(jd.strip()) >= 15:
        b, a = cur["before"], cur["after"]
        c1, c2 = st.columns(2)
        c1.metric("ATS score before", b["score"])
        c2.metric("ATS score after", a["score"], a["score"] - b["score"])
        for n in cur["notes"]:
            st.write("- " + n)
        plain = _plain_text(cur["curated"])
        st.text_area("Tailored resume (plain text)", plain, height=400)
        st.download_button("Download as .txt", plain, file_name="tailored_resume.txt")

# ---------------- interview quiz ----------------
with tab_quiz:
    if len(jd.strip()) < 15:
        st.info("Paste the job description first. The quiz uses your projects and the job post.")
    else:
        if st.button("Build interview quiz"):
            try:
                st.session_state["quiz"] = build_questions(resume_text, jd)
                st.session_state["qi"] = 0
                st.session_state["results"] = {}
            except Exception as e:
                st.error(f"Could not generate questions: {e}")
        quiz = st.session_state.get("quiz")
        if quiz and quiz["questions"]:
            qs, i = quiz["questions"], st.session_state["qi"]
            results = st.session_state["results"]
            q = qs[i]
            st.progress((i + 1) / len(qs), text=f"Question {i + 1} of {len(qs)}  ·  {q['category']}")
            st.subheader(q["question"])
            st.caption(f"Why asked: {q['why']}  |  Tip: {q['tip']}")
            ans = st.text_area("Your answer", key=f"ans_{q['id']}", height=140)
            b1, b2, b3 = st.columns(3)
            if b1.button("Check answer", key=f"chk_{q['id']}"):
                results[q["id"]] = grade_answer(q, ans)
            if b2.button("Get AI feedback", key=f"fb_{q['id']}"):
                with st.spinner("Asking the model..."):
                    st.session_state[f"fb_text_{q['id']}"] = ai_feedback(q, ans) or "MODEL_ERROR"
            r = results.get(q["id"])
            if r:
                (st.success if r["verdict"] == "correct" else st.warning)(f"{r['verdict'].title()} · score {r['score']}/100")
                for x in r["good"]:
                    st.write("✅ " + x)
                for x in r["improve"]:
                    st.write("➕ " + x)
                with st.expander("Model answer"):
                    st.write(r["model_answer"])
                if r.get("note"):
                    st.caption(r["note"])
            fb = st.session_state.get(f"fb_text_{q['id']}")
            if fb == "MODEL_ERROR":
                st.error("The model could not be reached. The instant check above still works.")
            elif fb:
                st.info(fb)
            n1, n2 = st.columns(2)
            if n1.button("◀ Previous", disabled=i == 0):
                st.session_state["qi"] = i - 1
                st.rerun()
            if n2.button("Next ▶", disabled=i == len(qs) - 1):
                st.session_state["qi"] = i + 1
                st.rerun()
            if results:
                avg = sum(x["score"] for x in results.values()) / len(results)
                st.metric("Average score so far", f"{avg:.0f}/100", f"{len(results)} answered")
