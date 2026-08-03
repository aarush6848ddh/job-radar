"""Throwaway: run Stage 2 (cached) then Stage 3 classify backfill over the survivors.

First run is a ~20-25 min throttled cold backfill; results land in
output/classifications.json so every rerun after is instant.
"""
import json

from funnel.embed_filter import embed_and_filter
from funnel.classify import classify

POSTINGS_PATH = "output/postings.jsonl"


def main():
    with open(POSTINGS_PATH) as f:
        postings = [json.loads(line) for line in f]

    stage2 = embed_and_filter(postings)          # cached vectors -> instant
    print(f"Stage 2 kept {len(stage2)} / {len(postings)}")

    kept = classify(stage2)                       # throttled cold backfill
    print(f"Stage 3 kept {len(kept)} / {len(stage2)}")

    dropped = [p for p in stage2 if not p["classify_pass"]]
    print("\nStage 3 DROPPED:")
    for p in dropped:
        print(f"  {p['title']} ({p['company']}) -> {p['classify_reason']}")


if __name__ == "__main__":
    main()
