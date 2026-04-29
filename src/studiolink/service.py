from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from studiolink.ollama_adapter import OllamaAdapter
from studiolink.lmstudio_adapter import LMStudioAdapter
from studiolink.config import StudioLinkConfig
from studiolink.models import (
    DoctorCheck,
    ImportMode,
    LinkMode,
    ModelReadiness,
    OllamaModel,
    SyncRecord,
    SyncResult,
)
from studiolink.state import StateStore
from studiolink.syncer import Syncer

if TYPE_CHECKING:
    from studiolink.ports import LMStudioPort, OllamaPort

logger = logging.getLogger("studiolink")


@dataclass(slots=True, frozen=True)
class StatusEntry:
    model: OllamaModel
    synced: bool
    sync_record: SyncRecord | None

    @property
    def display_status(self) -> str:
        if self.synced:
            return "synced"
        if self.model.readiness is ModelReadiness.STALE:
            return "stale"
        if self.model.readiness is ModelReadiness.INVALID:
            return "invalid"
        return "pending"


class StudioLinkService:
    def __init__(
        self,
        config: StudioLinkConfig | None = None,
        ollama: "OllamaPort | None" = None,
        lmstudio: "LMStudioPort | None" = None,
    ) -> None:
        self.config = config or StudioLinkConfig.from_env()
        self.ollama = ollama if ollama else OllamaAdapter(self.config)
        self.lmstudio = lmstudio if lmstudio else LMStudioAdapter(self.config)
        self.state = StateStore(self.config.state_file)

    def scan(self) -> list[OllamaModel]:
        logger.debug(
            "Scanning Ollama manifests at %s", self.config.ollama_manifests_dir
        )
        models = self.ollama.scan_models()
        logger.debug("Discovered %d model(s)", len(models))
        return models

    def status(self) -> list[StatusEntry]:
        models = self.scan()
        records = self.state.get_all_records()
        return [
            StatusEntry(
                model=model,
                synced=self._is_currently_synced(
                    model, records.get(model.canonical_name)
                ),
                sync_record=records.get(model.canonical_name),
            )
            for model in models
        ]

    def sync(
        self,
        *,
        model_names: list[str] | None = None,
        sync_all: bool = False,
        link_mode: LinkMode | None = None,
        import_mode: ImportMode = ImportMode.ALIAS,
        dry_run: bool = False,
    ) -> list[SyncResult]:
        logger.debug(
            "Starting sync: sync_all=%s, link_mode=%s, import_mode=%s, dry_run=%s",
            sync_all,
            link_mode,
            import_mode,
            dry_run,
        )

        discovered = self.scan()

        if sync_all:
            selected = discovered
            logger.debug("Syncing all %d discovered model(s)", len(selected))
        else:
            selected = self._select_models(discovered, model_names or [])
            logger.debug(
                "Syncing selected model(s): %s", [m.canonical_name for m in selected]
            )

        mode = link_mode or self.config.default_link_mode
        syncer = Syncer(self.config, self.lmstudio, self.state)
        return syncer.sync(selected, mode, import_mode, dry_run)

    def doctor(self) -> list[DoctorCheck]:
        checks = [
            DoctorCheck(
                "ollama executable",
                self.config.ollama_exe.exists(),
                str(self.config.ollama_exe),
            ),
            DoctorCheck(
                "lm studio executable",
                self.config.lms_exe.exists(),
                str(self.config.lms_exe),
            ),
            DoctorCheck(
                "ollama manifests dir",
                self.config.ollama_manifests_dir.exists(),
                str(self.config.ollama_manifests_dir),
            ),
            DoctorCheck(
                "ollama blobs dir",
                self.config.ollama_blobs_dir.exists(),
                str(self.config.ollama_blobs_dir),
            ),
            DoctorCheck(
                "lm studio models dir",
                self.config.lmstudio_models_dir.exists(),
                str(self.config.lmstudio_models_dir),
            ),
            DoctorCheck(
                "hard-link volume compatibility",
                self.config.import_staging_dir.drive.lower()
                == self.config.lmstudio_models_dir.drive.lower(),
                f"{self.config.import_staging_dir.drive} -> {self.config.lmstudio_models_dir.drive}",
            ),
        ]

        try:
            version = self.lmstudio.get_version()
            logger.debug("Doctor: LM Studio version = %s", version)
            checks.append(
                DoctorCheck(
                    "lm studio cli version",
                    version is not None,
                    version or "no version output",
                )
            )
        except Exception as exc:
            logger.debug("Doctor: LM Studio version check failed: %s", exc)
            checks.append(DoctorCheck("lm studio cli version", False, str(exc)))

        try:
            capabilities = self.lmstudio.get_import_capabilities()
            logger.debug("Doctor: LM Studio import capabilities = %s", capabilities)
            checks.append(
                DoctorCheck(
                    "lm studio import capabilities",
                    bool(capabilities),
                    ", ".join(sorted(c.value for c in capabilities)) or "none",
                )
            )
        except Exception as exc:
            logger.debug("Doctor: LM Studio capabilities check failed: %s", exc)
            checks.append(
                DoctorCheck("lm studio import capabilities", False, str(exc))
            )

        models = self.scan()
        checks.append(
            DoctorCheck(
                "discovered ollama models",
                True,
                f"{len(models)} model(s)",
            )
        )

        stale_models = [
            m for m in models if m.readiness is ModelReadiness.STALE
        ]
        checks.append(
            DoctorCheck(
                "ollama blob presence",
                not stale_models,
                ", ".join(m.canonical_name for m in stale_models)
                if stale_models
                else "all present",
            )
        )

        valid_gguf = [m for m in models if m.gguf_valid]
        checks.append(
            DoctorCheck(
                "gguf header validation",
                len(valid_gguf) == len(models),
                f"{len(valid_gguf)}/{len(models)} passed validation",
            )
        )

        checks.append(
            DoctorCheck(
                "import alias directory",
                self.config.import_staging_dir.exists(),
                str(self.config.import_staging_dir),
            )
        )

        return checks

    @staticmethod
    def _is_currently_synced(model: OllamaModel, record: SyncRecord | None) -> bool:
        if record is None:
            return False
        if record.digest != model.model_digest:
            return False
        if record.link_mode is None:
            return False
        return True

    def _select_models(
        self, discovered: list[OllamaModel], requested_names: list[str]
    ) -> list[OllamaModel]:
        if not requested_names:
            raise ValueError("provide at least one model name or use --all")

        lookup: dict[str, list[OllamaModel]] = {}
        for model in discovered:
            for key in {
                model.canonical_name,
                model.fully_qualified_name,
                model.short_name,
                model.repository,
            }:
                lookup.setdefault(key, []).append(model)

        selected: list[OllamaModel] = []
        for name in requested_names:
            matches = lookup.get(name, [])
            if not matches:
                available = ", ".join(sorted(lookup.keys()))
                raise ValueError(
                    f"model not found: {name}. Available: {available}"
                )
            selected.extend(matches)

        return selected