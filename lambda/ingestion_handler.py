import os
from datetime import datetime, timezone
from pathlib import Path

import boto3  

from run_local import fetch_all_ats, dedup, is_target_cycle, is_recent, load_yaml
from ingestion.github_repos import fetch_github_repos

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

    # 4. Serialize to JSONL (one Posting per line) so the M720q side is a verbatim passthrough download.
    body = "\n".join(p.to_json() for p in unique)

    # 5. Write to S3. Bucket name comes from an env var on the function.
    bucket = os.environ["POSTINGS_BUCKET"]
    key = f"raw-postings/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode())

    # 6. Return a small summary so it lands in CloudWatch logs.
    return {"fetched": len(all_postings), "kept": len(unique), "key": key}
