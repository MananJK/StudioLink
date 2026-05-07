from __future__ import annotations

import json
import logging
from pathlib import Path

from studiolink.models import SyncRecord

class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get_record(self, name: str) -> SyncRecord | None:
        """Get a single sync record by model name."""
        records = self._load_raw()
        record_data = records.get(name)
        if record_data and isinstance(record_data, dict):
            return SyncRecord.from_json(record_data)
        return None
    
    def get_all_records(self) -> dict[str, SyncRecord]:
        """Get all sync records."""
        records = self._load_raw()
        return {
            name: SyncRecord.from_json(record)
            for name, record in records.items()
            if isinstance(record, dict)
        }
    
    def upsert(self, record: SyncRecord) -> None:
        """Insert or update a sync record."""
        records = self._load_raw()
        records[record.canonical_name] = record.to_json()
        self._save_raw(records)

    def remove(self, name: str) -> None:
        """Delete a sync record by model name"""
        records = self._load_raw()
        if name in records:
            del records[name]
            self._save_raw(records)

    def save_all(self, records: dict[str, SyncRecord]) -> None:
        """Save all sync records at once (bulk operation)."""
        records_json = {name: record.to_json() for name, record in records.items()}
        self._save_raw(records_json)
    
    def _save_raw(self, records: dict[str, object]) -> None:
        """Save raw JSON dict to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "sync_records": records,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_raw(self) -> dict[str, object]:
        """Load raw JSON dict from disk."""
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logging.warning(
                "Corrupted state file at %s: %s. Starting fresh.", self.path, exc
            )
            return {}
        return payload.get("sync_records", {})