from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from studiolink.models import LinkMode


def _expand_path(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else default.expanduser()


def _default_ollama_exe(home: Path) -> Path:
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return Path(shutil.which("ollama") or "/usr/bin/ollama")


def _default_lms_exe(home: Path) -> Path:
    if sys.platform == "win32":
        return home / ".lmstudio" / "bin" / "lms.exe"
    return Path(shutil.which("lms") or home / ".lmstudio" / "bin" / "lms")


@dataclass(slots=True, frozen=True)
class StudioLinkConfig:
    ollama_exe: Path
    lms_exe: Path
    ollama_models_dir: Path
    ollama_manifests_dir: Path
    ollama_blobs_dir: Path
    lmstudio_models_dir: Path
    state_dir: Path
    state_file: Path
    import_staging_dir: Path
    default_link_mode: LinkMode = LinkMode.HARD_LINK

    @classmethod
    def from_env(cls) -> "StudioLinkConfig":
        home = Path.home()
        # Honor Ollama's own OLLAMA_MODELS relocation variable unless the
        # StudioLink-specific override is set.
        ollama_models_dir = _expand_path(
            "STUDIOLINK_OLLAMA_MODELS_DIR",
            _expand_path("OLLAMA_MODELS", home / ".ollama" / "models"),
        )
        state_dir = _expand_path("STUDIOLINK_STATE_DIR", home / ".studiolink")
        return cls(
            ollama_exe=_expand_path(
                "STUDIOLINK_OLLAMA_EXE",
                _default_ollama_exe(home),
            ),
            lms_exe=_expand_path(
                "STUDIOLINK_LMS_EXE",
                _default_lms_exe(home),
            ),
            ollama_models_dir=ollama_models_dir,
            ollama_manifests_dir=ollama_models_dir / "manifests",
            ollama_blobs_dir=ollama_models_dir / "blobs",
            lmstudio_models_dir=_expand_path(
                "STUDIOLINK_LMSTUDIO_MODELS_DIR",
                home / ".lmstudio" / "models",
            ),
            state_dir=state_dir,
            state_file=state_dir / "state.json",
            import_staging_dir=state_dir / "imports",
        )
