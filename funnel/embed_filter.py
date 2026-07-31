import html
import os
import json
import hashlib
import yaml
import numpy as np
import google.generativeai as genai
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from pathlib import Path

load_dotenv()
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

EMBED_MODEL = "models/gemini-embedding-001"
PROFILE_PATH = "config/profile.yaml"
PROFILE_VECTOR_PATH = "output/profile_vector.json"

def clean_description(raw: str, max_chars: int = 2000) -> str:
    unescaped = html.unescape(raw)
    text = BeautifulSoup(unescaped, "html.parser").get_text(separator=" ")
    text = " ".join(text.split())
    return text[:max_chars]

def embed_text(text: str, task_type: str) ->  list[float]:
    result = genai.embed_content(model=EMBED_MODEL, content=text, task_type=task_type, output_dimensionality=768)
    return result["embedding"]

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def load_profile_vector() -> list[float]:
    cache = Path(PROFILE_VECTOR_PATH)
    with open(PROFILE_PATH) as f:
        profile_text = yaml.safe_load(f)["profile"]
    current_hash = _hash(profile_text)

    if cache.exists():
        with open(cache) as f:
            cached = json.load(f)
        if cached.get("hash") == current_hash:
            return cached["vector"]

    vector = embed_text(profile_text, "RETRIEVAL_QUERY")
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "w") as f:
        json.dump({"hash": current_hash, "vector": vector}, f)
    return vector 

def cosine_similarity(a: list[float], b: list[float]) -> float:
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def embed_and_filter(postings: list[dict]) -> list[dict]:
    profile_vec = load_profile_vector()
    with open(PROFILE_PATH) as f:
        threshold = yaml.safe_load(f)["threshold"]
    
    # Phase A: build every doc_text, then embed them all in batches
    doc_texts = [
        f"{p['title']} at {p['company']}. {clean_description(p['raw_description'])}"
        for p in postings
    ]
    doc_vecs = embed_batch(doc_texts, "RETRIEVAL_DOCUMENT")

    # Phase B: score + filter (no API calls in this loop anymore)
    kept = []
    for p, doc_vec in zip(postings, doc_vecs):
        score = cosine_similarity(profile_vec, doc_vec)
        if score >= threshold:
            p["embed_score"] = round(float(score), 4)
            kept.append(p)

    kept.sort(key=lambda x: x["embed_score"], reverse=True)
    return kept

def embed_batch(texts: list[str], task_type: str, batch_size: int = 50) -> list[list[float]]:
    vectors = []
    for i in range (0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        result = genai.embed_content(model=EMBED_MODEL, content=chunk, task_type=task_type, output_dimensionality=768)
        vectors.extend(result["embedding"])
    return vectors
