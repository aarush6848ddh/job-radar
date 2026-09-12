#!/usr/bin/env python3
"""Publish a failed JobRadar unit's recent journal to the jobradar-alerts SNS
topic. Invoked by jobradar-failure@.service via systemd OnFailure=, so a silent
chain failure becomes an email instead of a days-later "why hasn't the sheet
updated" discovery.

The box has no aws CLI, so this publishes via boto3 using a dedicated,
least-privilege profile (jobradar-alerter: sns:Publish on this one topic only,
kept separate from jobradar-reader's S3-read boundary).
"""
import socket
import subprocess
import sys
from datetime import datetime, timezone

import boto3

TOPIC_ARN = "arn:aws:sns:us-east-1:593793068467:jobradar-alerts"
AWS_PROFILE = "jobradar-alerter"
REGION = "us-east-1"


def main() -> None:
    # OnFailure=jobradar-failure@%n.service passes the failed unit name as %i.
    unit = sys.argv[1] if len(sys.argv) > 1 else "jobradar.service"
    host = socket.gethostname()
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Last lines of the failed run carry the cause, so the email is actionable
    # without SSHing into the box.
    try:
        log = subprocess.run(
            ["journalctl", "--user", "-u", unit, "-n", "25", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        ).stdout or "(journal empty)"
    except Exception as e:
        log = f"(could not read journal: {e})"

    subject = f"JobRadar FAILED: {unit} on {host}"[:100]  # SNS subject hard cap
    body = (
        "JobRadar chain failed.\n\n"
        f"Unit: {unit}\n"
        f"Host: {host}\n"
        f"Time: {when} (UTC)\n\n"
        "--- last 25 journal lines ---\n"
        f"{log}"
    )

    session = boto3.Session(profile_name=AWS_PROFILE)
    session.client("sns", region_name=REGION).publish(
        TopicArn=TOPIC_ARN, Subject=subject, Message=body,
    )


if __name__ == "__main__":
    main()
