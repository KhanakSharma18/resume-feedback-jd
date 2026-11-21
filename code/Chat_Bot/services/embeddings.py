"""
Semantic matching with sentence embeddings.

Why sentence-transformers (and not word2vec / GloVe)?
  word2vec and GloVe give one vector per WORD, so a sentence is just an average of word vectors, which
  blurs meaning and cannot tell "built a REST API" from "consumed a REST API". Sentence-transformer models
  embed the whole sentence, so "Developed backend endpoints in Flask" lands close to "Experience building
  REST APIs with Python" even though they share almost no words. all-MiniLM-L6-v2 is small (~80 MB),
  fast on a plain CPU and a standard choice for this job.

Everything here is optional:
  * the model loads lazily on first use (or in the background at startup, see warm_up())
  * if sentence-transformers is not installed, or RESUME_EMBEDDINGS=off, every function returns None
    and the rest of the app falls back to TF-IDF only.

    pip install sentence-transformers
"""
import os
import re
import threading

try:
    import numpy as np
except Exception:  # numpy missing -> semantic features simply stay off
    np = None

MODEL_NAME = os.environ.get("RESUME_EMBED_MODEL", "all-MiniLM-L6-v2")
DISABLED = os.environ.get("RESUME_EMBEDDINGS", "on").strip().lower() in ("off", "0", "false", "no")

# Calibration: MiniLM cosine of ~0.20 means "unrelated", ~0.60 means "clearly the same idea".
SEM_LOW, SEM_HIGH = 0.20, 0.60
SEM_COVERED = 0.40          # a job requirement counts as covered if some resume line scores at least this

_lock = threading.Lock()
_model = None
_failed = False
_cache = {}
_MAX_CACHE = 5000


def _load():
    global _model, _failed
    if _model is not None or _failed or DISABLED or np is None:
        return _model
    with _lock:
        if _model is not None or _failed:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL_NAME)
            print(f"[embeddings] loaded {MODEL_NAME}")
        except Exception as e:
            _failed = True
            print(f"[embeddings] semantic matching is OFF ({type(e).__name__}: {e}). "
                  f"Install with: pip install sentence-transformers")
    return _model


def available():
    return _load() is not None


def warm_up():
    """Load the model in a background thread so the first request is not slow."""
    if DISABLED:
        return
    threading.Thread(target=_load, daemon=True).start()


def status():
    return {"enabled": not DISABLED, "loaded": _model is not None, "failed": _failed, "model": MODEL_NAME}


# ----------------------------------------------------------------------
# Encoding
# ----------------------------------------------------------------------
def encode(texts):
    """List of strings -> (n, dim) array of unit vectors, or None when embeddings are unavailable."""
    texts = list(texts)
    model = _load()
    if model is None or not texts:
        return None
    missing = [t for t in dict.fromkeys(texts) if t not in _cache]
    if missing:
        if len(_cache) + len(missing) > _MAX_CACHE:
            _cache.clear()
        vecs = model.encode(missing, normalize_embeddings=True, convert_to_numpy=True,
                            show_progress_bar=False, batch_size=32)
        for t, v in zip(missing, vecs):
            _cache[t] = v
    return np.vstack([_cache[t] for t in texts])


def best_matches(queries, corpus):
    """
    For every query text, the most similar corpus text.
    Returns a list of (score, corpus_index) in the order of `queries`, or None if unavailable.
    """
    if not queries or not corpus:
        return None
    q, c = encode(queries), encode(corpus)
    if q is None or c is None:
        return None
    sims = q @ c.T
    idx = sims.argmax(axis=1)
    return [(float(sims[i, j]), int(j)) for i, j in enumerate(idx)]


def similarity(a, b):
    """Cosine similarity of two texts (0..1), or None."""
    v = encode([a, b])
    if v is None:
        return None
    return float(max(0.0, v[0] @ v[1]))


# ----------------------------------------------------------------------
# Text -> meaningful lines (bullets are re-joined when the PDF wrapped them)
# ----------------------------------------------------------------------
_BULLET = re.compile(r"^\s*[\u25cf\u2022\u25aa\u25e6\-\*\u2013]\s+(.*)$")


def semantic_chunks(text, max_chunks=120):
    """One chunk per bullet / sentence, with wrapped PDF lines glued back together."""
    items, cur, cur_is_bullet = [], "", False

    def flush():
        nonlocal cur
        if cur.strip():
            items.append(cur.strip())
        cur = ""

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        m = _BULLET.match(raw)
        if m:
            flush()
            cur, cur_is_bullet = m.group(1).strip(), True
        elif len(line.split()) <= 3 and not line.endswith((".", ",")) and (line.isupper() or line.istitle()):
            flush()                                    # looks like a heading
            cur_is_bullet = False
        elif cur and cur_is_bullet and not cur.endswith("."):
            cur += " " + line                          # wrapped bullet
        else:
            flush()
            cur, cur_is_bullet = line, False
    flush()

    out = []
    for it in items:
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z])", it):
            if len(sent.split()) >= 4:
                out.append(" ".join(sent.split())[:300])
    return out[:max_chunks]


# ----------------------------------------------------------------------
# Resume vs job description
# ----------------------------------------------------------------------
def semantic_match(resume, jd):
    """
    For each requirement line of the job post, find the resume line closest in meaning.
    Returns None when embeddings are unavailable, otherwise
      {"percent": 0-100, "average": float, "evidence": [{"requirement", "resume_line", "score"}]}
    """
    r_chunks, j_chunks = semantic_chunks(resume), semantic_chunks(jd, max_chunks=60)
    hits = best_matches(j_chunks, r_chunks)
    if hits is None:
        return None
    scores = [s for s, _ in hits]
    avg = sum(scores) / len(scores)
    pct = round(100 * min(1.0, max(0.0, (avg - SEM_LOW) / (SEM_HIGH - SEM_LOW))))
    ranked = sorted(zip(j_chunks, hits), key=lambda x: -x[1][0])
    evidence = [{"requirement": req[:200], "resume_line": r_chunks[i][:200], "score": round(s, 2)}
                for req, (s, i) in ranked if s >= SEM_COVERED][:4]
    return {"percent": int(pct), "average": round(avg, 3), "evidence": evidence}
