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

MODEL = "openai/gpt-oss-120b"
PROFILE_PATH = "config/profile.yaml"
CLASSIFY_CACHE_PATH = "output/classifications.json"

def _cache_key(posting: dict, profile_text: str) -> str:
    return _hash(posting["id"] + profile_text)

def classify_one(posting: dict, profile_text: str) -> tuple[bool, str]:
    posting_text = (
        f"{posting['title']} at {posting['company']}. "
        f"{clean_description(posting['raw_description'], max_chars=1000)}"
    )

    messages = [
        {
            "role": "system",
            "content": (
                f"You are screening internships for this candidate: {profile_text}. "
                "Answer YES only if the role genuinely fits. Reject PhD-required, "
                "hardware, pure data-analyst, sales, and non-engineering roles. "
                'Respond with a JSON object: {"decision": "yes" or "no", "reason": "one sentence"}.'
            ),
        },
        {"role": "user", "content": posting_text},
    ]

    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )

    parsed = json.loads(resp.choices[0].message.content)
    decision = parsed["decision"].strip().lower() == "yes"
    reason = parsed["reason"]
    return decision, reason

def classify(postings: list[dict]) -> list[dict]:
    with open(PROFILE_PATH) as f:
        profile_text = yaml.safe_load(f)["profile"]

    path = Path(CLASSIFY_CACHE_PATH)
    if path.exists():
        with open(path) as f:
            cache = json.load(f)
    else:
        cache = {}

    kept = []
    for p in postings:
        key = _cache_key(p, profile_text)
        if key in cache:
            decision, reason = cache[key]
        else:
            decision, reason = classify_one(p, profile_text)
            cache[key] = (decision, reason)
            time.sleep(5)  # throttle real calls only; TPM 8K / ~550 tok = ~14/min

        p["classify_pass"] = decision
        p["classify_reason"] = reason
        if decision:
            kept.append(p)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f)

    return kept