import re 
import requests
import logging
from bs4 import BeautifulSoup
from schema import Posting, make_posting_id
from ingestion.ats import _title_matches

# GitHub repo parser - fetches README files and extracts job postings from tables.
# Handles both HTML tables (SimplifyJobs) and markdown pipe tables (speedyapply).
# Uses BeautifulSoup to parse both formats uniformly.

logger = logging.getLogger(__name__)

def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r'[^\x00-\x7F]+', '', text) # remove emoji
    text = text.replace('↳', '').strip()
    return text

def _extract_link(cell) -> str:
    tag = cell.find("a", href=re.compile(r'^https?://'))
    return tag["href"] if tag else ""

def _fetch_readme(repo: str, branch: str) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/README.md"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"{repo}: README fetch failed - {e}")
        return ""


def _parse_table_rows(html: str, repo: str) -> list[Posting]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    postings = []
    last_company = ""

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            company_text = _clean(cells[0].get_text())
            if not company_text:
                company_text = last_company
            else:
                last_company = company_text

            title = _clean(cells[1].get_text())
            location = _clean(cells[2].get_text())
            url = _extract_link(cells[3])

            if not title or not url:
                continue

            posting = Posting(
                id=make_posting_id(company_text, title, location),
                company=company_text,
                title=title,
                location=location,
                url=url,
                source="github_repo",
                source_detail=repo,
                posted_at=None,
                raw_description="",
            )
            postings.append(posting)

    return postings


def _parse_markdown_table(md: str, repo: str) -> list[Posting]:
    postings = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # split into cells: strip the outer pipes, then split on "|"
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:           # need at least through the Posting column (idx 4)
            continue

        company = _clean(BeautifulSoup(cells[0], "html.parser").get_text())
        title = _clean(cells[1])
        location = _clean(cells[2])
        # column layout varies (some tables drop the Salary column), so scan
        # every cell after the company for the first real link - the apply URL
        url = ""
        for cell in cells[1:]:
            url = _extract_link(BeautifulSoup(cell, "html.parser"))
            if url:
                break

        if not title or not url:
            continue

        if not _title_matches(title):
            continue

        postings.append(Posting(
            id=make_posting_id(company, title, location),
            company=company,
            title=title,
            location=location,
            url=url,
            source="github_repo",
            source_detail=repo,
            posted_at=None,
            raw_description="",
        ))
    return postings
        

def fetch_github_repos(repos: list[dict]) -> list[Posting]:
    all_postings = []
    for entry in repos:
        repo = entry["repo"]
        branch = entry["branch"]
        readme = _fetch_readme(repo, branch)
        if not readme:
            continue

        fmt = entry["format"]
        if fmt == "html":
            postings = _parse_table_rows(readme, repo)
        elif fmt == "markdown":
            postings = _parse_markdown_table(readme, repo)
        else:
            logger.warning("Unknown format '%s' for repo '%s', skipping", fmt, repo)
            continue
        logger.info(f"{repo}: found {len(postings)} postings")
        all_postings.extend(postings)
    return all_postings