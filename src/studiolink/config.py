from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from studiolink.models import LinkMode


def _expand_path(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name)
    return Path(raw).expanduser() if raw else default.expanduser()


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
        ollama_models_dir = _expand_path(
            "STUDIOLINK_OLLAMA_MODELS_DIR",
            home / ".ollama" / "models",
        )
        state_dir = _expand_path("STUDIOLINK_STATE_DIR", home / ".studiolink")
        return cls(
            ollama_exe=_expand_path(
                "STUDIOLINK_OLLAMA_EXE",
                home / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
            ),
            lms_exe=_expand_path(
                "STUDIOLINK_LMS_EXE",
                home / ".lmstudio" / "bin" / "lms.exe",
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
