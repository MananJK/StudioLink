from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from studiolink.config import StudioLinkConfig
from studiolink.models import LinkMode, ModelReadiness
from studiolink.ollama_adapter import OllamaAdapter


class OllamaAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".test-tmp" / f"ollama-adapter-{uuid.uuid4().hex}"
        root = self.root
        self.ollama_models = root / "ollama" / "models"
        self.manifests_dir = self.ollama_models / "manifests"
        self.blobs_dir = self.ollama_models / "blobs"
        self.manifests_dir.mkdir(parents=True)
        self.blobs_dir.mkdir(parents=True)
        self.config = StudioLinkConfig(
            ollama_exe=root / "ollama.exe",
            lms_exe=root / "lms.exe",
            ollama_models_dir=self.ollama_models,
            ollama_manifests_dir=self.manifests_dir,
            ollama_blobs_dir=self.blobs_dir,
            lmstudio_models_dir=root / "lmstudio" / "models",
            state_dir=root / "state",
            state_file=root / "state" / "state.json",
            import_staging_dir=root / "state" / "imports",
            default_link_mode=LinkMode.HARD_LINK,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scan_models_reads_valid_manifest(self) -> None:
        digest = "sha256:1234abcd"
        blob = self.blobs_dir / "sha256-1234abcd"
        blob.write_bytes(b"GGUF" + b"\x00" * 8)

        manifest_path = self.manifests_dir / "registry.ollama.ai" / "library" / "deepseek-r1" / "8b"
        manifest_path.parent.mkdir(parents=True)
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

        models = OllamaAdapter(self.config).scan_models()
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model.canonical_name, "deepseek-r1:8b")
        self.assertEqual(model.user_repo, "ollama/deepseek-r1")
        self.assertTrue(model.gguf_valid)
        self.assertEqual(model.readiness, ModelReadiness.READY)
        self.assertEqual(model.blob_path, blob)
        self.assertEqual(model.issues, ())

    def test_scan_models_marks_missing_blob_as_stale(self) -> None:
        digest = "sha256:5678efgh"

        manifest_path = self.manifests_dir / "registry.ollama.ai" / "library" / "embeddinggemma" / "300m"
        manifest_path.parent.mkdir(parents=True)
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

        models = OllamaAdapter(self.config).scan_models()
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertFalse(model.gguf_valid)
        self.assertEqual(model.readiness, ModelReadiness.STALE)
        self.assertIn("model blob is missing from the Ollama blob store", model.issues)

    def test_scan_models_flags_non_gguf_blob_as_invalid(self) -> None:
        digest = "sha256:5678efgh"
        blob = self.blobs_dir / "sha256-5678efgh"
        blob.write_bytes(b"NOTG" + b"\x00" * 8)

        manifest_path = self.manifests_dir / "registry.ollama.ai" / "custom" / "my-model" / "latest"
        manifest_path.parent.mkdir(parents=True)
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

        models = OllamaAdapter(self.config).scan_models()
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertFalse(model.gguf_valid)
        self.assertEqual(model.readiness, ModelReadiness.INVALID)
        self.assertIn("blob does not start with GGUF magic bytes", model.issues)

    def test_scan_models_flags_missing_model_layer_as_invalid(self) -> None:
        manifest_path = self.manifests_dir / "registry.ollama.ai" / "library" / "broken-model" / "latest"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps({"layers": []}), encoding="utf-8")

        models = OllamaAdapter(self.config).scan_models()
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model.readiness, ModelReadiness.INVALID)
        self.assertIn("missing Ollama model layer", model.issues)


if __name__ == "__main__":
    unittest.main()
