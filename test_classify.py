"""Throwaway: run classify_one on the first posting to sanity-check the parse."""
import json

import yaml

from funnel.classify import classify_one

with open("output/postings.jsonl") as f:
    posting = json.loads(f.readline())

with open("config/profile.yaml") as f:
    profile_text = yaml.safe_load(f)["profile"]

decision, reason = classify_one(posting, profile_text)
print(posting["title"], "|", posting["company"])
print(decision, "|", reason)
