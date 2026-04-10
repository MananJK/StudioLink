from __future__ import annotations

import json
from pathlib import Path

from studiolink.models import SyncRecord


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, SyncRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records = payload.get("sync_records", {})
        return {
            name: SyncRecord.from_json(record)
            for name, record in records.items()
            if isinstance(record, dict)
        }

    def save(self, records: dict[str, SyncRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "sync_records": {
                name: record.to_json()
                for name, record in sorted(records.items())
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def upsert(self, record: SyncRecord) -> None:
        records = self.load()
        records[record.canonical_name] = record
        self.save(records)
