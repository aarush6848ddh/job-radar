import json
import argparse

from funnel.seen_store import SeenStore
from funnel.embed_filter import embed_and_filter
from funnel.classify import classify
from funnel.score import score

POSTINGS_PATH = "output/postings.jsonl"
RANKED_PATH = "output/ranked.jsonl"

def load_postings(path: str) -> list[dict]:
    postings = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                postings.append(json.loads(line))
    return postings

def run_funnel(fresh: bool = False) -> list[dict]:
    store = SeenStore()
    if fresh:
        store.reset()

    postings = load_postings(POSTINGS_PATH)

    # Stage 1: drop already-seen
    new = [p for p in postings if not store.check(p["id"])]

    # Stage 2 -> 3 -> 4: each only sees the prior stage's survivors
    stage2 = embed_and_filter(new)
    stage3 = classify(stage2)
    ranked = score(stage3)

    # Option B: mark ONLY final survivors seen. "Seen" means "delivered to the user," not "evaluated once,"
    # so postings dropped under an old profile/threshold get a fair re-check on the next run (near-free via caches).
    for p in ranked:
        store.mark_seen(p["id"])

    with open(RANKED_PATH, "w") as f:
        for p in ranked:
            f.write(json.dumps(p) + "\n")

    print(
        f"{len(postings)} in -> {len(new)} new -> {len(stage2)} embed "
        f"-> {len(stage3)} classify -> {len(ranked)} ranked"
    )

    return ranked

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    run_funnel(fresh=args.fresh)
