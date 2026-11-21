from flask import Flask, render_template, request, jsonify, session
from services.assistant import process_command
from services.resume_analyzer import analyze_ats, ai_review
from services.resume_curator import curate_resume
from services.interview import build_questions
from services.quiz import grade_answer, ai_feedback
from services import embeddings
import os
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')  # Needed for session; set SECRET_KEY in real use

# Upload folder
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# -----------------------------
# ROUTE: Home page
# -----------------------------
@app.route("/")
def index():
    return render_template("index.html")


# -----------------------------
# ROUTE: Legacy /process (kept exactly same)
# -----------------------------
@app.route("/process", methods=["POST"])
def process():
    command = request.json.get("command", "")
    use_pdf = request.json.get("use_pdf", True)
    pdf_text = session.get('pdf_text', None)

    # use PDF only if checkbox is on AND PDF is uploaded
    if use_pdf and pdf_text:
        response = process_command(command, pdf_text=pdf_text)
    else:
        response = process_command(command)

    return jsonify({"response": response})


# -----------------------------
# ROUTE: /ask (main chat endpoint for your new UI)
# -----------------------------
@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    user_message = data.get("message", "")
    chat_id = data.get("chatId", "")

    # match frontend flag
    use_pdf = data.get("use_pdf", True)
    pdf_text = session.get('pdf_text', None)

    # Select processing method
    if use_pdf and pdf_text:
        reply = process_command(user_message, pdf_text=pdf_text)
    else:
        reply = process_command(user_message)

    # The frontend REQUIRES {"reply": "..."}
    return jsonify({"reply": reply})


# -----------------------------
# ROUTE: Upload + extract PDF
# -----------------------------
@app.route("/upload_pdf", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF allowed"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    # Extract PDF text
    try:
        reader = PdfReader(filepath)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        session['pdf_text'] = text
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# ROUTE: Resumelyzer panel (ATS score / weaknesses / improvements)
# -----------------------------
@app.route("/resume_analyze", methods=["POST"])
def resume_analyze():
    data = request.get_json(silent=True) or {}
    kind = data.get("type", "ats")                 # "ats" | "weaknesses" | "improve"
    job_description = data.get("job_description", "")

    pdf_text = session.get("pdf_text")
    if not pdf_text or not pdf_text.strip():
        return jsonify({"error": "No readable resume found. Attach your resume as a PDF first "
                                 "(scanned image PDFs have no text to read)."}), 400

    try:
        result = analyze_ats(pdf_text, job_description)   # rules + skills database + semantic match
    except Exception as e:  # never send an HTML error page to the browser
        return jsonify({"error": f"Could not analyse the resume: {e}"}), 500

    # optional slower AI review from the Llama model
    if data.get("ai") and kind in ("weaknesses", "improve"):
        result["ai_text"] = ai_review(pdf_text, kind, job_description)

    return jsonify(result)


# -----------------------------
# ROUTE: Curate the resume for a job description (the browser builds the PDF)
# -----------------------------
@app.route("/resume_curate", methods=["POST"])
def resume_curate():
    data = request.get_json(silent=True) or {}
    job_description = (data.get("job_description") or "").strip()

    pdf_text = session.get("pdf_text")
    if not pdf_text or not pdf_text.strip():
        return jsonify({"error": "No readable resume found. Attach your resume as a PDF first."}), 400
    if len(job_description) < 15:
        return jsonify({"error": "Paste the job description first."}), 400

    try:
        return jsonify(curate_resume(pdf_text, job_description))
    except Exception as e:  # never send an HTML error page to the browser
        return jsonify({"error": f"Could not tailor the resume: {e}"}), 500


# -----------------------------
# ROUTE: Interview questions from the resume's projects + the job description
# -----------------------------
@app.route("/interview_questions", methods=["POST"])
def interview_questions():
    data = request.get_json(silent=True) or {}
    job_description = (data.get("job_description") or "").strip()

    pdf_text = session.get("pdf_text")
    if not pdf_text or not pdf_text.strip():
        return jsonify({"error": "No readable resume found. Attach your resume as a PDF first."}), 400
    if len(job_description) < 15:
        return jsonify({"error": "Paste the job description first."}), 400

    try:
        return jsonify(build_questions(pdf_text, job_description))
    except Exception as e:
        return jsonify({"error": f"Could not generate questions: {e}"}), 500


# -----------------------------
# ROUTE: Check one quiz answer (instant, offline)
# -----------------------------
@app.route("/quiz_check", methods=["POST"])
def quiz_check():
    data = request.get_json(silent=True) or {}
    question = data.get("question") or {}
    if not question.get("question"):
        return jsonify({"error": "No question received."}), 400
    try:
        return jsonify(grade_answer(question, data.get("answer", "")))
    except Exception as e:
        return jsonify({"error": f"Could not check the answer: {e}"}), 500


# -----------------------------
# ROUTE: Written feedback on one answer from the Llama model (slow, optional)
# -----------------------------
@app.route("/quiz_ai_feedback", methods=["POST"])
def quiz_ai_feedback():
    data = request.get_json(silent=True) or {}
    question = data.get("question") or {}
    if not question.get("question"):
        return jsonify({"error": "No question received."}), 400
    return jsonify({"text": ai_feedback(question, data.get("answer", ""))})


# -----------------------------
# Run the server
# -----------------------------
if __name__ == "__main__":
    # load the sentence-transformer in the background (only in the reloader's child process, so it loads once)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        embeddings.warm_up()
    app.run(debug=True)
