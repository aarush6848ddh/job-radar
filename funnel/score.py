import os
import json
import time
import yaml
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from funnel.embed_filter import clean_description, _hash # reuse Stage 2 helpers

load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])

MODEL = "openai/gpt-oss-20b"   # Stage 4: separate bucket from Stage 3's 120b
PROFILE_PATH = "config/profile.yaml"
SCORE_CACHE_PATH = "output/scores.json"

WEIGHTS = {"fit": 0.4, "interest": 0.4, "seniority": 0.2}  # tune freely, no re-prompt

def _cache_key(posting: dict, profile_text: str) -> str:
    # same invalidation logic as Stage 3, profile edits bust the cache
    return _hash(posting["id"] + profile_text)

def score_one(posting: dict, profile_text: str) -> dict:
    posting_text = (
        f"{posting['title']} at {posting['company']}. "
        f"{clean_description(posting['raw_description'], max_chars=1000)}"
    )

    messages = [
        {
            "role": "system",
            "content": (
                f"You are scoring an internship posting for this candidate: {profile_text}. "
                "Score the posting on three axes, each 0-100:\n"
                "fit - how well the role's tech stack and domain match the candidate's background\n"
                "seniority - how genuinely intern-level the role is (100 = clearly an internship, "
                "0 = actually a disguised senior/full-time role)\n"
                "interest - how well the role matches the candidate's stated interests "
                "(forward deployed engineering, agentic systems, LLM engineering)\n"
                'Respond with a JSON object exactly in this shape: '
                '{"fit": int, "seniority": int, "interest": int, "reason": "one sentence"}.'
            ),
        },
        {"role": "user", "content": posting_text},
    ]

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0,  # deterministic output so the id+profile cache key maps to a stable result
        response_format={"type": "json_object"},
    )

    parsed = json.loads(resp.choices[0].message.content)
    fit = int(parsed["fit"])
    seniority = int(parsed["seniority"])
    interest = int(parsed["interest"])
    reason = parsed["reason"]

    # Combine in Python (not in the prompt) so weights can be retuned freely without re-prompting or busting the cache.
    total = (
        WEIGHTS["fit"] * fit
        + WEIGHTS["seniority"] * seniority
        + WEIGHTS["interest"] * interest
    )

    return {
        "fit": fit,
        "seniority": seniority,
        "interest": interest,
        "total": round(total, 1),
        "reason": reason,
    }

SAVE_EVERY = 25  # incremental cache flush cadence; a mid-run crash keeps completed calls

def _save_cache(path: Path, cache: dict) -> None:
    # Atomic write (temp + replace) so an interrupted flush can't corrupt the cache.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, path)

def score(postings: list[dict]) -> list[dict]:
    with open(PROFILE_PATH) as f:
        profile_text = yaml.safe_load(f)["profile"]

    path = Path(SCORE_CACHE_PATH)
    if path.exists():
        with open(path) as f:
            cache = json.load(f)
    else:
        cache = {}

    since_save = 0
    for p in postings:
        key = _cache_key(p, profile_text)
        if key in cache:
            result = cache[key]
        else:
            result = score_one(p, profile_text)
            cache[key] = result
            since_save += 1
            if since_save >= SAVE_EVERY:
                _save_cache(path, cache)  # don't lose a long backfill to a mid-run crash
                since_save = 0
            time.sleep(5)   # throttle real calls only (8K TPM / ~550 tok)

        # Nest under one key so Stage 4 output doesn't collide with embed_score / classify_reason.
        p["score"] = result

    _save_cache(path, cache)
    return sorted(postings, key=lambda p: p["score"]["total"], reverse=True)