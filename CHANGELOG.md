# Changelog

Dated list of changes since Milestone 1.
## 2026-10-20  Skill extraction
- Replaced the hard-coded keyword list with a skills database (`data/skills_db.json`, 247 skills, categories and aliases).
- Added optional spaCy NER to spot tools in a job post that the database does not know.

## 2026-10-30  Semantic matching
- Added sentence-transformer embeddings (`all-MiniLM-L6-v2`) so resume lines are compared with job requirements by meaning, not only by words.
- Job match is now a blend of keyword coverage, TF-IDF and semantic similarity; falls back to TF-IDF if the model is not installed.

## 2026-11-10  Interview quiz
- New popup quiz built from the resume's projects and the job post: type or speak answers, instant check, model answer, final score.
- 93 technical questions with model answers (`data/question_bank.json`).
- Optional AI feedback on an answer (prompt P4).

## 2026-11-15  UI
- Removed the "Use PDF" checkbox (an attached PDF is now used automatically).
- Chat area in one centred card; new dark theme.

## 2026-11-18  Security clean-up
- Removed hard-coded API keys and the Hugging Face token; keys now come from environment variables / Colab Secrets.
- Colab notebook accepts optional `system` and `temperature` for prompt experiments.

## Prompt work (add your own entries)
- 2026-11-19  v1 prompts saved in `prompts/v1/`
- 2026-11-19 v2: (what you changed and why)
- 2026-11-20  v3: (what you changed and why)
