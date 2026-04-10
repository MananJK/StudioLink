from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from studiolink.config import StudioLinkConfig
from studiolink.lmstudio_adapter import LMStudioAdapter
from studiolink.models import DoctorCheck, LinkMode, ModelReadiness, OllamaModel, SyncRecord, SyncResult
from studiolink.ollama_adapter import OllamaAdapter
from studiolink.state import StateStore


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
    def __init__(self, config: StudioLinkConfig | None = None) -> None:
        self.config = config or StudioLinkConfig.from_env()
        self.ollama = OllamaAdapter(self.config)
        self.lmstudio = LMStudioAdapter(self.config)
        self.state = StateStore(self.config.state_file)

    def scan(self) -> list[OllamaModel]:
        return self.ollama.scan_models()

    def status(self) -> list[StatusEntry]:
        models = self.scan()
        records = self.state.load()
        return [
            StatusEntry(
                model=model,
                synced=self._is_currently_synced(model, records.get(model.canonical_name)),
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
        dry_run: bool = False,
    ) -> list[SyncResult]:
        discovered = self.scan()
        if sync_all:
            selected = discovered
        else:
            selected = self._select_models(discovered, model_names or [])

        records = self.state.load()
        mode = link_mode or self.config.default_link_mode
        results: list[SyncResult] = []

        for model in selected:
            existing = records.get(model.canonical_name)
            if self._is_currently_synced(model, existing):
                results.append(
                    SyncResult(
                        model=model,
                        status="skipped",
                        message="already synced according to StudioLink state",
                        record=existing,
                    )
                )
                continue

            if model.readiness is ModelReadiness.STALE:
                results.append(
                    SyncResult(
                        model=model,
                        status="error",
                        message=(
                            "model blob is missing from the Ollama blob store; "
                            f"run `ollama pull {model.canonical_name}` to restore it"
                        ),
                    )
                )
                continue

            if model.readiness is ModelReadiness.INVALID or model.blob_path is None or model.model_digest is None:
                results.append(
                    SyncResult(
                        model=model,
                        status="error",
                        message="model is not ready for import: " + "; ".join(model.issues or ("unknown error",)),
                    )
                )
                continue

            alias_path, alias_created = self._ensure_import_alias(model)
            try:
                import_result = self.lmstudio.import_model(
                    str(alias_path),
                    user_repo=model.user_repo,
                    link_mode=mode,
                    dry_run=dry_run,
                )
            finally:
                if dry_run and alias_created and alias_path.exists():
                    alias_path.unlink()

            record = SyncRecord(
                canonical_name=model.canonical_name,
                digest=model.model_digest,
                blob_path=model.blob_path,
                import_alias_path=alias_path,
                user_repo=model.user_repo,
                link_mode=mode,
                imported_at=datetime.now(tz=timezone.utc),
                import_command=import_result.command,
            )

            if not dry_run:
                records[record.canonical_name] = record
                self.state.save(records)

            results.append(
                SyncResult(
                    model=model,
                    status="dry-run" if dry_run else "synced",
                    message=self._format_import_message(import_result),
                    record=record,
                )
            )

        return results

    def doctor(self) -> list[DoctorCheck]:
        checks = [
            DoctorCheck("ollama executable", self.config.ollama_exe.exists(), str(self.config.ollama_exe)),
            DoctorCheck("lm studio executable", self.config.lms_exe.exists(), str(self.config.lms_exe)),
            DoctorCheck("ollama manifests dir", self.config.ollama_manifests_dir.exists(), str(self.config.ollama_manifests_dir)),
            DoctorCheck("ollama blobs dir", self.config.ollama_blobs_dir.exists(), str(self.config.ollama_blobs_dir)),
            DoctorCheck("lm studio models dir", self.config.lmstudio_models_dir.exists(), str(self.config.lmstudio_models_dir)),
            DoctorCheck(
                "hard-link volume compatibility",
                self.config.import_staging_dir.drive.lower() == self.config.lmstudio_models_dir.drive.lower(),
                f"{self.config.import_staging_dir.drive} -> {self.config.lmstudio_models_dir.drive}",
            ),
        ]

        try:
            version = self.lmstudio.get_version()
            checks.append(DoctorCheck("lm studio cli version", version is not None, version or "no version output"))
        except Exception as exc:
            checks.append(DoctorCheck("lm studio cli version", False, str(exc)))

        try:
            capabilities = self.lmstudio.get_import_capabilities()
            checks.append(
                DoctorCheck(
                    "lm studio import capabilities",
                    LinkMode.HARD_LINK in capabilities,
                    ", ".join(sorted(mode.value for mode in capabilities)) if capabilities else "no import modes detected",
                )
            )
        except Exception as exc:
            checks.append(DoctorCheck("lm studio import capabilities", False, str(exc)))

        discovered = self.scan()
        checks.append(DoctorCheck("discovered ollama models", bool(discovered), f"{len(discovered)} model(s)"))
        stale = [model.canonical_name for model in discovered if model.readiness is ModelReadiness.STALE]
        checks.append(
            DoctorCheck(
                "ollama blob presence",
                not stale,
                "all discovered models have local blobs" if not stale else ", ".join(stale),
            )
        )

        invalid = [model.canonical_name for model in discovered if model.readiness is ModelReadiness.INVALID]
        checks.append(
            DoctorCheck(
                "gguf header validation",
                not invalid,
                "all discovered model blobs passed GGUF validation" if not invalid else ", ".join(invalid),
            )
        )

        alias_check_ok, alias_details = self._check_alias_creation()
        checks.append(DoctorCheck("import alias directory", alias_check_ok, alias_details))
        return checks

    def _select_models(self, discovered: list[OllamaModel], requested_names: list[str]) -> list[OllamaModel]:
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
                raise ValueError(f"model '{name}' was not found in Ollama manifests")
            if len(matches) > 1:
                raise ValueError(f"model name '{name}' is ambiguous; use a tag such as '{matches[0].canonical_name}'")
            selected.append(matches[0])
        return selected

    def _ensure_import_alias(self, model: OllamaModel) -> tuple[Path, bool]:
        assert model.blob_path is not None
        self.config.import_staging_dir.mkdir(parents=True, exist_ok=True)
        alias_path = self.config.import_staging_dir / model.import_filename
        if alias_path.exists():
            return alias_path, False
        os.link(model.blob_path, alias_path)
        return alias_path, True

    @staticmethod
    def _is_currently_synced(model: OllamaModel, record: SyncRecord | None) -> bool:
        if model.readiness is not ModelReadiness.READY:
            return False
        if record is None:
            return False
        if record.digest != model.model_digest:
            return False
        if not record.import_alias_path.exists():
            return False
        return True

    @staticmethod
    def _format_import_message(result: object) -> str:
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        text = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
        return text or "LM Studio import completed"

    def _check_alias_creation(self) -> tuple[bool, str]:
        try:
            self.config.import_staging_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, str(exc)
        return True, str(self.config.import_staging_dir)
