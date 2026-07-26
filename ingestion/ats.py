import re
import requests
import logging
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
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
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
                raw_description=job.get("content", ""),
            )
            postings.append(posting)
        return postings
    except requests.RequestException as e:
        logger.warning(f"{company}: Greenhouse fetch failed - {e}")
        return []


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
            posting = Posting(
                id=make_posting_id(company, title, location),
                company=company,
                title=title,
                location=location,
                url=job.get("hostedUrl", ""),
                source="lever",
                source_detail=slug,
                posted_at=job.get("createdAt"),
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
        resp = requests.post(url, timeout=10)
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