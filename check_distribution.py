"""Throwaway diagnostic: embed all postings and print the score distribution.

Triggers the one-time doc-vector backfill on first run, then reads the cache.
Use the printed percentiles to choose the Stage 2 threshold in config/profile.yaml.
"""
import json

import numpy as np

from funnel.embed_filter import (
    load_doc_vectors,
    load_profile_vector,
    cosine_similarity,
)

POSTINGS_PATH = "output/postings.jsonl"


def main():
    with open(POSTINGS_PATH) as f:
        postings = [json.loads(line) for line in f]

    profile_vec = load_profile_vector()
    doc_vecs = load_doc_vectors(postings)  # backfill on first run, cache after

    scored = [
        (cosine_similarity(profile_vec, doc_vecs[p["id"]]), p["title"], p["company"])
        for p in postings
    ]
    scored.sort(reverse=True)

    scores = np.array([s for s, _, _ in scored])
    print(f"n = {len(scores)}")
    for pct in (0, 10, 25, 50, 75, 90, 100):
        print(f"  p{pct:>3} = {np.percentile(scores, pct):.4f}")

    print("\nTop 15:")
    for s, title, company in scored[:15]:
        print(f"  {s:.4f}  {title}  ({company})")

    print("\nBottom 15:")
    for s, title, company in scored[-15:]:
        print(f"  {s:.4f}  {title}  ({company})")


if __name__ == "__main__":
    main()
