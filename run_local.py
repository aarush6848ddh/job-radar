import json
import logging
import re
from pathlib import Path
import yaml

from ingestion.ats import fetch_greenhouse, fetch_lever, fetch_ashby
from ingestion.github_repos import fetch_github_repos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dispatch table: platform name -> fetcher function.
# Each fetcher has the same signature (company, slug) -> list[Posting]

FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}

def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def fetch_all_ats(companies: list[dict]) -> list:
    postings = []
    for c in companies:
        fetcher = FETCHERS.get(c["platform"])
        if not fetcher:
            logger.warning("Unknown platform '%s' for company '%s', skipping", c["platform"], c["name"])
            continue
        postings.extend(fetcher(c["name"], c["slug"]))
    return postings

# keep 2027 explicitly; otherwise drop anything naming an older cycle (2010-2026)
_OFF_CYCLE_RE = re.compile(r"\b20(?:1\d|2[0-6])\b")

def is_target_cycle(title: str) -> bool:
    if "2027" in title:
        return True
    return not _OFF_CYCLE_RE.search(title)

def dedup(postings: list) -> list:
    unique = {}
    for p in postings:
        unique[p.id] = p
    return list(unique.values())

def write_jsonl(postings: list, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for p in postings:
            f.write(p.to_json() + "\n")

def main():
    companies = load_yaml("config/companies.yaml")["companies"]
    repos = load_yaml("config/repos.yaml")["repos"]

    all_postings = fetch_all_ats(companies) + fetch_github_repos(repos)
    unique = dedup(all_postings)
    unique = [p for p in unique if is_target_cycle(p.title)]

    logger.info("Fetched %d postings, %d unique", len(all_postings), len(unique))
    write_jsonl(unique, "output/postings.jsonl")

if __name__ == "__main__":
    main()