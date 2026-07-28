import json
from pathlib import Path
from datetime import datetime, timezone

class SeenStore:
    def __init__(self, path: str = "output/seen_ids.json"):
        self.path = Path(path)
        if self.path.exists():
            with open(self.path) as f:
                self._seen = json.load(f)
        else:
            self._seen = {}

    def check(self, posting_id: str) -> bool:
        return posting_id in self._seen

    def mark_seen(self, posting_id: str) -> None:
        self._seen[posting_id] = datetime.now(timezone.utc).isoformat()
        self._save()

    def reset(self) -> None:
        self._seen = {}
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._seen, f)