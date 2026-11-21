# Resume Feedback Against a Job Description

SCSE4041 Mini Project, Milestone 2. Upload a resume (PDF), paste a job description, and get feedback: an ATS-style score,
a job match with matched and missing skills, written advice from an LLM, a job-tailored resume PDF, and an interview practice quiz
built from your own projects.

**Prototype link:** `PASTE YOUR COLAB / PROTOTYPE LINK HERE`

## Team
S24CSEU0009
S24CSEU1783
S24CSEU1054
S24CSEU1067
S24CSEU2292
S24CSEU2006


Team ID: PE-B49-22  |  Team name: ghaziabaddies |  Faculty: Ankit Vijay Bansal

## How it works
1. **Rule-based layer (code):** PDF text extraction, ATS scoring, skills database, TF-IDF + sentence-embedding match to the job post.
2. **LLM layer (prompts):** Llama 3.1 8B Instruct gives written weaknesses and improvements (prompts P1, P2), answers questions about the PDF (P3) and reviews interview answers (P4). Prompt files are in `prompts/`.
3. **Quiz:** questions come from your projects and the job post; answers are checked by key concepts or a rubric.

## Run it
You need Python 3.10+ and a Google Colab account (free GPU) for the Llama model.

```bash
# 1. start the model: open code/notebook/Llama_3_1_8B_Api.ipynb in Google Colab
#    - add your Hugging Face token in Colab Secrets as HF_TOKEN (never paste it into the notebook)
#    - run all cells and copy the public URL it prints

# 2. run the app
cd code/Chat_Bot
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Windows PowerShell:  $env:LLAMA_API_URL = "https://xxxx.trycloudflare.com/query"
# macOS/Linux:         export LLAMA_API_URL="https://xxxx.trycloudflare.com/query"
python app.py          # open http://127.0.0.1:5000
```
Without the Llama URL the rule-based features still work; only the AI review, PDF chat and AI feedback need it.
Optional: `NEWS_API_KEY` (news command), `SECRET_KEY` (Flask sessions), `RESUME_EMBEDDINGS=off` (turn off semantic matching).
Try it with `test-data/sample_resume_fake.pdf` and `test-data/sample_job_description_fullstack.txt`.

## Repository layout
```
README.md   CHANGELOG.md
prompts/    v1/  v2/  v3/  final/      prompt versions, one .txt per prompt
code/       Chat_Bot/ (Flask app)  notebook/ (Colab Llama server)
test-data/  sample inputs, test table template, saved outputs
docs/       diagrams and the Milestone 2 PDF
```

## Known limitations
- The AI review only reads the first 6000 characters of a resume and 3000 of a job post; the model answers up to 512 tokens.
- Scanned (image-only) PDFs have no text to read.
- The Colab link changes every session, so the model must be restarted and the URL updated before use.
- Quiz marking is keyword/rubric based; a correct answer in very different words can be under-scored.

## Security
No API keys or tokens are stored in this repository. Use environment variables and Colab Secrets.
