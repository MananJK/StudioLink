from __future__ import annotations

import shutil
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from studiolink.models import LinkMode, SyncRecord
from studiolink.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        root = Path.cwd() / ".test-tmp" / f"state-store-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        path = root / "state.json"
        store = StateStore(path)
        record = SyncRecord(
            canonical_name="deepseek-r1:8b",
            digest="sha256:abc",
            blob_path=Path("C:/models/blob"),
            import_alias_path=Path("C:/state/import.gguf"),
            user_repo="ollama/deepseek-r1",
            link_mode=LinkMode.HARD_LINK,
            imported_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
            import_command=("lms", "import"),
        )
        store.save({"deepseek-r1:8b": record})

        records = store.load()
        self.assertEqual(records["deepseek-r1:8b"], record)

    def test_load_corrupted_state_file_returns_empty_dict(self) -> None:
        root = Path.cwd() / ".test-tmp" / f"state-store-corrupt-{uuid.uuid4().hex}"
        root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        path = root / "state.json"
        path.write_text("not valid json {", encoding="utf-8")
        store = StateStore(path)

        records = store.load()
        self.assertEqual(records, {})


if __name__ == "__main__":
    unittest.main()
