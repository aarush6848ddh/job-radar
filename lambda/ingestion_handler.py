import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3

from run_local import fetch_all_ats, dedup, is_target_cycle, is_recent, is_us_location, load_yaml
from ingestion.ats import hydrate_greenhouse
from ingestion.github_repos import fetch_github_repos

logger = logging.getLogger(__name__)

# Per-run kept ~= the 24h fresh-US volume (is_recent uses a 24h window, so each 6h run
# re-includes the whole window). Warn well before Stage 3's ~360/day Groq TPD ceiling so
# an approaching wall is loud in CloudWatch, not discovered as a failure.
VOLUME_WARN_THRESHOLD = 300

# Configs are bundled with the deployment zip. Resolve them relative to THIS
# file, not the cwd (Lambda cwd is /var/task, not your repo root).
# When you build the zip, copy config/ in as a sibling of this handler so this
# path resolves. Adjust the subpath if you bundle them somewhere else.
_CONFIG_DIR = Path(__file__).parent / "config"


def handler(event, context):
    # 1. Load the bundled YAML configs (companies + repos).
    companies = load_yaml(str(_CONFIG_DIR / "companies.yaml"))["companies"]
    repos = load_yaml(str(_CONFIG_DIR / "repos.yaml"))["repos"]

    # 2. Fetch + combine, exactly like run_local.main().
    all_postings = fetch_all_ats(companies) + fetch_github_repos(repos)

    # 3. Same within-batch dedup + 2027-cycle filter as local.
    unique = dedup(all_postings)
    unique = [p for p in unique if is_target_cycle(p.title)]
    unique = [p for p in unique if is_recent(p)]
    unique = [p for p in unique if is_us_location(p)]

    # 3b. Hydrate deferred greenhouse descriptions for survivors only (kept light at fetch).
    hydrate_greenhouse(unique)

    if len(unique) >= VOLUME_WARN_THRESHOLD:
        logger.warning("fresh-US volume %d approaching Groq Stage-3 daily ceiling (~360)", len(unique))

    # 4. Serialize to JSONL (one Posting per line) so the M720q side is a verbatim passthrough download.
    body = "\n".join(p.to_json() for p in unique)

    # 5. Write to S3. Bucket name comes from an env var on the function.
    bucket = os.environ["POSTINGS_BUCKET"]
    key = f"raw-postings/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode())

    # 6. Return a small summary so it lands in CloudWatch logs.
    return {"fetched": len(all_postings), "kept": len(unique), "key": key}
