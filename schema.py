# Unified posting schema - every source normalizes into this shape.
# make_posting_id hashes company+title+location for deterministic dedup.

from dataclasses import dataclass, asdict
from typing import Optional
import hashlib
import json

@dataclass
class Posting:
    id: str
    company: str
    title: str
    location: str
    url: str
    source: str
    source_detail: str
    posted_at: Optional[str]
    raw_description: str 

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

def make_posting_id(company: str, title: str, location: str) -> str:
    key = f"{company}{title}{location}".lower()
    return hashlib.sha256(key.encode()).hexdigest()
