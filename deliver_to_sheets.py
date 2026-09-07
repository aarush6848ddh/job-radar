import os 
import json
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

RANKED_PATH = "output/ranked.jsonl"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER = ["Date Found", "Score", "Company", "Role", "Location", "Apply Link", "Reason", "Posted"]


def load_ranked(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    ranked = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                ranked.append(json.loads(line))
    return ranked


def row_from_posting(p: dict, delivered_at: str) -> list:
    score = p.get("score", {})
    return [
        delivered_at,
        score.get("total", ""),
        p.get("company", ""),
        p.get("title", ""),
        p.get("location", ""),
        p.get("url", ""),
        score.get("reason", ""),
        p.get("posted_at") or "",
    ]


def deliver():
    ranked = load_ranked(RANKED_PATH)
    if not ranked:
        print("Nothing to deliver")
        return

    creds = Credentials.from_service_account_file(
       os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"], scopes=SCOPES
    )
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(os.environ["SHEETS_SPREADSHEET_ID"])
    ws = sh.sheet1

    delivered_at = datetime.now(timezone.utc).isoformat()
    rows = [row_from_posting(p, delivered_at) for p in ranked]

    # Header + data in ONE append. Two separate append_rows calls collide on a
    # brand-new sheet (gspread re-detects the table range per call), which drops
    # the header. Prepend it here so the whole batch lands in a single call.
    # get_all_values() returns [] on a pristine sheet but [[]] after clear(), so
    # test for "no non-empty cell" rather than == [].
    existing = ws.get_all_values()
    if not any(cell for row in existing for cell in row):
        rows = [HEADER] + rows

    ws.append_rows(rows, value_input_option="RAW")

    print(f"Appended {len(rows)} rows to sheet")


if __name__ == "__main__":
    deliver()