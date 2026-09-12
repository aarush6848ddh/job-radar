import re
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from schema import Posting, make_posting_id

# ATS fetchers - one function per platform (Greenhouse, Lever, Ashby).
# Each hits a public API, filters for intern-related titles, and returns Postings.
# On any error, logs a warning and returns [] so the pipeline keeps running.

logger = logging.getLogger(__name__)

TITLE_KEYWORDS = ["intern", "internship", "co-op", "coop", "university", "campus"]
# word-boundary match so "intern" hits "Software Intern" but not "International"
_TITLE_RE = re.compile(r"\b(" + "|".join(TITLE_KEYWORDS) + r")\b", re.IGNORECASE)

def _title_matches(title: str) -> bool:
    return bool(_TITLE_RE.search(title))

def fetch_greenhouse(company: str, slug: str) -> list[Posting]:
    # No content=true: the board list is fetched light (title/location/updated_at only).
    # Descriptions are hydrated later via hydrate_greenhouse() for post-filter survivors
    # only, so we don't download every job's full HTML across thousands of boards.
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        jobs = resp.json()["jobs"]
        postings = []
        for job in jobs:
            title = job.get("title", "")
            if not _title_matches(title):
                continue
            location = job.get("location", {}).get("name", "")
            posting = Posting(
                id=make_posting_id(company, title, location),
                company=company,
                title=title,
                location=location,
                url=job.get("absolute_url", ""),
                source="greenhouse",
                source_detail=slug,
                posted_at=job.get("updated_at"),
                raw_description="",  # deferred; filled by hydrate_greenhouse()
            )
            postings.append(posting)
        return postings
    except requests.RequestException as e:
        logger.warning(f"{company}: Greenhouse fetch failed - {e}")
        return []


_GH_JOB_ID_RE = re.compile(r"/jobs/(\d+)")

def _hydrate_one(p: Posting) -> None:
    # Greenhouse per-job endpoint returns the full description content for a single job.
    m = _GH_JOB_ID_RE.search(p.url or "")
    if not m:
        return
    url = f"https://boards-api.greenhouse.io/v1/boards/{p.source_detail}/jobs/{m.group(1)}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        p.raw_description = resp.json().get("content", "")
    except requests.RequestException as e:
        logger.warning(f"{p.company}: Greenhouse content hydrate failed - {e}")

def hydrate_greenhouse(postings: list[Posting]) -> None:
    # Fill raw_description for greenhouse postings that had content deferred at list-fetch
    # time. Call AFTER the recency/US filters so only the handful of survivors are hydrated.
    # Mutates postings in place. Lever/Ashby carry descriptions in their list responses, so
    # they need no hydration.
    todo = [p for p in postings if p.source == "greenhouse" and not p.raw_description]
    if not todo:
        return
    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(_hydrate_one, todo))


def fetch_lever(company: str, slug: str) -> list[Posting]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        jobs = resp.json()
        postings = []
        for job in jobs:
            title = job.get("text", "")
            if not _title_matches(title):
                continue
            location = job.get("categories", {}).get("location", "")
            # createdAt is epoch MILLIS; normalize to canonical ISO 8601 UTC, or None
            ms = job.get("createdAt")
            posted_at = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None
            posting = Posting(
                id=make_posting_id(company, title, location),
                company=company,
                title=title,
                location=location,
                url=job.get("hostedUrl", ""),
                source="lever",
                source_detail=slug,
                posted_at=posted_at,
                raw_description=job.get("descriptionPlain", ""),
            )
            postings.append(posting)
        return postings
    except requests.RequestException as e:
        logger.warning(f"{company}: Lever fetch failed - {e}")
        return []

def fetch_ashby(company: str, slug: str) -> list[Posting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        postings = []
        for job in jobs:
            title = job.get("title", "")
            if not _title_matches(title):
                continue
            location = job.get("location", "")
            posting = Posting(
                id=make_posting_id(company, title, location),
                company=company,
                title=title,
                location=location,
                url=job.get("jobUrl", ""),
                source="ashby",
                source_detail=slug,
                posted_at=job.get("publishedAt"),
                raw_description=job.get("descriptionHtml", ""),
            )
            postings.append(posting)
        return postings
    except requests.RequestException as e:
        logger.warning(f"{company}: Ashby fetch failed - {e}")
        return []