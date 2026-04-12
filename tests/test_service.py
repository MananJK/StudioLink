from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from studiolink.config import StudioLinkConfig
from studiolink.models import ImportResult, LinkMode
from studiolink.service import StudioLinkService


class FakeLMStudioAdapter:
    def __init__(self) -> None:
        self.import_calls: list[tuple[str, str, LinkMode, bool]] = []

    def get_version(self) -> str:
        return "CLI commit: test"

    def get_import_capabilities(self) -> set[LinkMode]:
        return {LinkMode.HARD_LINK, LinkMode.COPY, LinkMode.SYMBOLIC_LINK}

    def import_model(
        self,
        source_path: str,
        *,
        user_repo: str,
        link_mode: LinkMode,
        dry_run: bool = False,
    ) -> ImportResult:
        self.import_calls.append((source_path, user_repo, link_mode, dry_run))
        return ImportResult(
            command=("lms", "import", source_path),
            stdout="imported",
            stderr="",
            return_code=0,
            dry_run=dry_run,
        )


class StudioLinkServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".test-tmp" / f"service-{uuid.uuid4().hex}"
        self.ollama_models = self.root / "ollama" / "models"
        self.manifests_dir = self.ollama_models / "manifests"
        self.blobs_dir = self.ollama_models / "blobs"
        self.manifests_dir.mkdir(parents=True)
        self.blobs_dir.mkdir(parents=True)
        self.config = StudioLinkConfig(
            ollama_exe=self.root / "ollama.exe",
            lms_exe=self.root / "lms.exe",
            ollama_models_dir=self.ollama_models,
            ollama_manifests_dir=self.manifests_dir,
            ollama_blobs_dir=self.blobs_dir,
            lmstudio_models_dir=self.root / "lmstudio" / "models",
            state_dir=self.root / "state",
            state_file=self.root / "state" / "state.json",
            import_staging_dir=self.root / "state" / "imports",
            default_link_mode=LinkMode.HARD_LINK,
        )
        self.service = StudioLinkService(self.config)
        self.service.lmstudio = FakeLMStudioAdapter()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_sync_stale_model_fails_with_repull_hint(self) -> None:
        self._write_manifest("embeddinggemma", "300m", "sha256:missing")

        results = self.service.sync(model_names=["embeddinggemma:300m"])

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.status, "error")
        self.assertIn("ollama pull embeddinggemma:300m", result.message)
        self.assertEqual(self.service.lmstudio.import_calls, [])

    def test_doctor_splits_blob_presence_and_gguf_validation(self) -> None:
        self._write_manifest("embeddinggemma", "300m", "sha256:missing")
        bad_blob = self.blobs_dir / "sha256-badblob"
        bad_blob.write_bytes(b"NOTG" + b"\x00" * 8)
        self._write_manifest("broken", "latest", "sha256:badblob")

        checks = {check.name: check for check in self.service.doctor()}

        self.assertFalse(checks["ollama blob presence"].ok)
        self.assertIn("embeddinggemma:300m", checks["ollama blob presence"].details)
        self.assertFalse(checks["gguf header validation"].ok)
        self.assertIn("broken:latest", checks["gguf header validation"].details)

    def test_status_marks_stale_models_distinctly(self) -> None:
        self._write_manifest("embeddinggemma", "300m", "sha256:missing")

        entries = self.service.status()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].display_status, "stale")

    def test_sync_all_continues_past_stale_models(self) -> None:
        ready_blob = self.blobs_dir / "sha256-readyblob"
        ready_blob.write_bytes(b"GGUF" + b"\x00" * 8)
        self._write_manifest("deepseek-r1", "8b", "sha256:readyblob")
        self._write_manifest("embeddinggemma", "300m", "sha256:missing")

        results = self.service.sync(sync_all=True, dry_run=True)

        self.assertEqual(len(results), 2)
        statuses = {result.model.canonical_name: result.status for result in results}
        self.assertEqual(statuses["deepseek-r1:8b"], "dry-run")
        self.assertEqual(statuses["embeddinggemma:300m"], "error")
        self.assertEqual(len(self.service.lmstudio.import_calls), 1)

    @patch("studiolink.service.os.link")
    @patch("studiolink.service.shutil.copy2")
    def test_sync_falls_back_to_copy_when_hard_link_fails(
        self, mock_copy2: object, mock_link: object
    ) -> None:
        """Test that sync falls back to copy mode when hard link fails (e.g., cross-volume)."""
        mock_link.side_effect = OSError("Invalid cross-device link")

        ready_blob = self.blobs_dir / "sha256-readyblob"
        ready_blob.write_bytes(b"GGUF" + b"\x00" * 8)
        self._write_manifest("deepseek-r1", "8b", "sha256:readyblob")

        results = self.service.sync(model_names=["deepseek-r1:8b"], dry_run=True)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "dry-run")
        # Verify os.link was attempted
        mock_link.assert_called_once()
        # Verify shutil.copy2 was used as fallback
        mock_copy2.assert_called_once()

    def _write_manifest(self, repository: str, tag: str, digest: str) -> None:
        manifest_path = (
            self.manifests_dir / "registry.ollama.ai" / "library" / repository / tag
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "layers": [
                        {
                            "mediaType": "application/vnd.ollama.image.model",
                            "digest": digest,
                            "size": 12,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
