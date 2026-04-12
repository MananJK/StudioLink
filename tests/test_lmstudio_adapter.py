from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from studiolink.config import StudioLinkConfig
from studiolink.lmstudio_adapter import LMStudioAdapter, LMStudioError
from studiolink.models import LinkMode


class LMStudioAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = StudioLinkConfig(
            ollama_exe=Path("/fake/ollama.exe"),
            lms_exe=Path("/fake/lms.exe"),
            ollama_models_dir=Path("/fake/ollama/models"),
            ollama_manifests_dir=Path("/fake/ollama/models/manifests"),
            ollama_blobs_dir=Path("/fake/ollama/models/blobs"),
            lmstudio_models_dir=Path("/fake/lmstudio/models"),
            state_dir=Path("/fake/state"),
            state_file=Path("/fake/state/state.json"),
            import_staging_dir=Path("/fake/state/imports"),
            default_link_mode=LinkMode.HARD_LINK,
        )
        self.adapter = LMStudioAdapter(self.config)

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_get_version_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="LM Studio CLI v0.2.0\n",
            stderr="",
            returncode=0,
        )

        version = self.adapter.get_version()

        self.assertEqual(version, "LM Studio CLI v0.2.0")
        mock_run.assert_called_once()

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_get_version_failure_raises_lmstudio_error(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=[str(self.config.lms_exe), "--version"],
            stderr="command not found",
        )

        with self.assertRaises(LMStudioError) as ctx:
            self.adapter.get_version()

        self.assertIn("Failed to get LM Studio version", str(ctx.exception))
        self.assertEqual(ctx.exception.return_code, 1)
        self.assertEqual(ctx.exception.stderr, "command not found")

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_get_import_capabilities_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="""
Usage: lms import [options] <path>

Options:
  --copy           Copy the model file
  --hard-link      Create a hard link
  --symbolic-link  Create a symbolic link
""",
            stderr="",
            returncode=0,
        )

        capabilities = self.adapter.get_import_capabilities()

        self.assertIn(LinkMode.COPY, capabilities)
        self.assertIn(LinkMode.HARD_LINK, capabilities)
        self.assertIn(LinkMode.SYMBOLIC_LINK, capabilities)

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_get_import_capabilities_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=127,
            cmd=[str(self.config.lms_exe), "import", "--help"],
            stderr="lms: command not found",
        )

        with self.assertRaises(LMStudioError) as ctx:
            self.adapter.get_import_capabilities()

        self.assertIn("Failed to get LM Studio import capabilities", str(ctx.exception))
        self.assertIn("command not found", str(ctx.exception))

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_import_model_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="Model imported successfully\n",
            stderr="",
            returncode=0,
        )

        result = self.adapter.import_model(
            "/path/to/model.gguf",
            user_repo="ollama/deepseek-r1",
            link_mode=LinkMode.HARD_LINK,
        )

        self.assertEqual(result.stdout, "Model imported successfully\n")
        self.assertEqual(result.return_code, 0)
        self.assertFalse(result.dry_run)
        mock_run.assert_called_once()

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_import_model_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=[str(self.config.lms_exe), "import", "/path/to/model.gguf"],
            stderr="Model file not found",
        )

        with self.assertRaises(LMStudioError) as ctx:
            self.adapter.import_model(
                "/path/to/model.gguf",
                user_repo="ollama/deepseek-r1",
                link_mode=LinkMode.HARD_LINK,
            )

        self.assertIn("LM Studio import failed", str(ctx.exception))
        self.assertIn("Model file not found", str(ctx.exception))

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_import_model_dry_run(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            stdout="Would import: /path/to/model.gguf\n",
            stderr="",
            returncode=0,
        )

        result = self.adapter.import_model(
            "/path/to/model.gguf",
            user_repo="ollama/deepseek-r1",
            link_mode=LinkMode.HARD_LINK,
            dry_run=True,
        )

        self.assertTrue(result.dry_run)
        # Verify --dry-run flag was passed
        call_args = mock_run.call_args[0][0]
        self.assertIn("--dry-run", call_args)

    @patch("studiolink.lmstudio_adapter.subprocess.run")
    def test_import_model_uses_correct_link_mode_flags(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

        for mode, expected_flag in [
            (LinkMode.HARD_LINK, "--hard-link"),
            (LinkMode.COPY, "--copy"),
            (LinkMode.SYMBOLIC_LINK, "--symbolic-link"),
        ]:
            with self.subTest(mode=mode):
                self.adapter.import_model(
                    "/path/to/model.gguf",
                    user_repo="ollama/test",
                    link_mode=mode,
                )
                call_args = mock_run.call_args[0][0]
                self.assertIn(expected_flag, call_args)


if __name__ == "__main__":
    unittest.main()
