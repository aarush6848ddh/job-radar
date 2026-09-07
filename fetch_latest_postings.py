import sys
import boto3
import botocore.exceptions

BUCKET = "jobradar-raw-postings-aarushsingh"
PREFIX = "raw-postings/"
OUT_PATH = "output/postings.jsonl"


def fetch_latest():
    session = boto3.Session(profile_name="jobradar-reader")
    s3 = session.client("s3")

    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX)

    if "Contents" not in response:
        print(f"No objects found under {PREFIX} in {BUCKET}", file=sys.stderr)
        sys.exit(1)

    latest_key = max(response["Contents"], key=lambda o: o["Key"])["Key"]

    obj = s3.get_object(Bucket=BUCKET, Key=latest_key)
    body = obj["Body"].read()

    with open(OUT_PATH, "wb") as f:
        f.write(body)

    line_count = body.count(b"\n") + 1
    print(f"Fetched {latest_key} -> {OUT_PATH} ({len(body)} bytes, {line_count} lines)")


if __name__ == "__main__":
    try:
        fetch_latest()
    except botocore.exceptions.ClientError as e:
        print(f"S3 error: {e}", file=sys.stderr)
        sys.exit(1)
    except botocore.exceptions.EndpointConnectionError as e:
        print(f"S3 unreachable: {e}", file=sys.stderr)
        sys.exit(1)
        
              