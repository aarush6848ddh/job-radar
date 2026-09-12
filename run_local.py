import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml

from ingestion.ats import fetch_greenhouse, fetch_lever, fetch_ashby, hydrate_greenhouse
from ingestion.github_repos import fetch_github_repos
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dispatch table: platform name -> fetcher function.
# Each fetcher has the same signature (company, slug) -> list[Posting]

FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}

WINDOW_HOURS = 24   # module constant so you can retune to 48 freely
FETCH_WORKERS = 24  # ATS fetches are I/O-bound; sequential over thousands of boards is a wall


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def _fetch_one(c: dict) -> list:
    fetcher = FETCHERS.get(c["platform"])
    if not fetcher:
        logger.warning("Unknown platform '%s' for company '%s', skipping", c["platform"], c["name"])
        return []
    return fetcher(c["name"], c["slug"])

def fetch_all_ats(companies: list[dict]) -> list:
    # Parallel: at thousands of companies a sequential loop cannot finish inside the
    # Lambda timeout. Each fetcher swallows its own errors and returns [].
    postings = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        for res in ex.map(_fetch_one, companies):
            postings.extend(res)
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

def is_recent(posting) -> bool:
    val = posting.posted_at
    if val is None:
        return False
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt) <= timedelta(hours=WINDOW_HOURS)

# 50 states + DC. Data, not logic.
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
# Comma-anchored state code, e.g. "Austin, TX". The comma is what stops a
# stray 2-letter token (or a non-US state like "KA") from matching.
_US_STATE_RE = re.compile(r",\s*(?:" + "|".join(sorted(_US_STATES)) + r")\b", re.IGNORECASE)
# Explicit country. Word-bounded, never bare "US" (too many in-word hits).
_US_COUNTRY_RE = re.compile(r"\b(?:united states|usa|u\.s\.a\.?|u\.s\.)\b", re.IGNORECASE)
# Hub-city allowlist for the bare-city case (no state code), e.g.
# "San Francisco, Seattle, New York City". Need not be exhaustive: obscure US
# cities always arrive as "City, ST", so only hubs ever appear bare.
_US_CITY_RE = re.compile(r"\b(?:" + "|".join([
    "san francisco", "seattle", "new york", "nyc", "los angeles", "chicago",
    "boston", "austin", "washington", "denver", "atlanta", "dallas", "houston",
    "philadelphia", "san diego", "san jose", "portland", "pittsburgh",
    "minneapolis", "miami",
]) + r")\b", re.IGNORECASE)
# Non-US blocklist. Word-bounded so "uk" can't match inside "Milwaukee" etc.
_NON_US_RE = re.compile(r"\b(?:" + "|".join([
    "dublin", "london", "singapore", "bucharest", "bengaluru", "bangalore",
    "toronto", "vancouver", "montreal", "canada", "india", "ireland", "uk",
    "united kingdom", "berlin", "paris", "amsterdam", "sydney", "tokyo",
    "tel aviv", "warsaw", "madrid", "munich", "zurich", "hong kong",
    "mexico city", "sao paulo",
]) + r")\b", re.IGNORECASE)

def is_us_location(posting) -> bool:
    loc = posting.location or ""
    # 1. Positive US signal wins first (resolves "Dublin, OH" / "Ontario, CA").
    if _US_STATE_RE.search(loc) or _US_COUNTRY_RE.search(loc) or _US_CITY_RE.search(loc):
        return True
    # 2. Explicit non-US signal.
    if _NON_US_RE.search(loc):
        return False
    # 3. Ambiguous ("Remote", "N/A", empty) -> drop, same call as undated.
    return False

def main():
    companies = load_yaml("config/companies.yaml")["companies"]
    repos = load_yaml("config/repos.yaml")["repos"]

    all_postings = fetch_all_ats(companies) + fetch_github_repos(repos)
    unique = dedup(all_postings)
    unique = [p for p in unique if is_target_cycle(p.title)]
    undated = [p for p in unique if p.posted_at is None]
    recent = [p for p in unique if is_recent(p)]
    logger.info("recency: kept %d, dropped %d (undated %d)", len(recent), len(unique) - len(recent), len(undated))
    unique = recent

    us = [p for p in unique if is_us_location(p)]
    logger.info("us: kept %d, dropped %d", len(us), len(unique) - len(us))
    unique = us

    hydrate_greenhouse(unique)  # fill deferred greenhouse descriptions for survivors only

    logger.info("Fetched %d postings, %d unique", len(all_postings), len(unique))
    write_jsonl(unique, "output/postings.jsonl")

if __name__ == "__main__":
    main()