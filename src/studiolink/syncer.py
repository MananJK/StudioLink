from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from studiolink.config import StudioLinkConfig
from studiolink.models import (
    ImportMode,
    LinkMode,
    ModelReadiness,
    OllamaModel,
    SyncRecord,
    SyncResult,
)
from studiolink.ports import LMStudioPort
from studiolink.state import StateStore
logger = logging.getLogger("studiolink")
class Syncer:
    def __init__(
        self,
        config: StudioLinkConfig,
        lmstudio: LMStudioPort,
        state: StateStore,
    ) -> None:
        self.config = config
        self.lmstudio = lmstudio
        self.state = state
    def sync(
        self,
        models: list[OllamaModel],
        link_mode: LinkMode,
        import_mode: ImportMode,
        dry_run: bool,
    ) -> list[SyncResult]:
        logger.debug(
            "Syncing %d model(s): link_mode=%s, import_mode=%s, dry_run=%s",
            len(models),
            link_mode,
            import_mode,
            dry_run,
        )
        records = self.state.load()
        logger.debug("Loaded %d existing sync record(s)", len(records))
        results: list[SyncResult] = []
        for model in models:
            result = self._sync_one(
                model, records, link_mode, import_mode, dry_run
            )
            results.append(result)
            if result.record and not dry_run:
                records[result.record.canonical_name] = result.record
                self.state.save(records)
                logger.debug("Saved sync record for %s", model.canonical_name)
        return results
    def _sync_one(
        self,
        model: OllamaModel,
        records: dict[str, SyncRecord],
        link_mode: LinkMode,
        import_mode: ImportMode,
        dry_run: bool,
    ) -> SyncResult:
        logger.debug(
            "Processing model: %s (readiness=%s)",
            model.canonical_name,
            model.readiness,
        )
        existing = records.get(model.canonical_name)
        if self._is_currently_synced(model, existing):
            logger.debug("Model %s is already synced, skipping", model.canonical_name)
            return SyncResult(
                model=model,
                status="skipped",
                message="already synced according to StudioLink state",
                record=existing,
            )
        if model.readiness is ModelReadiness.STALE:
            logger.debug("Model %s is stale (blob missing)", model.canonical_name)
            return SyncResult(
                model=model,
                status="error",
                message=(
                    "model blob is missing from the Ollama blob store; "
                    f"run `ollama pull {model.canonical_name}` to restore it"
                ),
            )
        if (
            model.readiness is ModelReadiness.INVALID
            or model.blob_path is None
            or model.model_digest is None
        ):
            logger.debug("Model %s is invalid: %s", model.canonical_name, model.issues)
            return SyncResult(
                model=model,
                status="error",
                message="model is not ready for import: "
                + "; ".join(model.issues or ("unknown error",)),
            )
        if import_mode is ImportMode.DIRECT:
            alias_path = model.blob_path
            alias_created = False
            logger.debug("Using Ollama blob directly: %s", alias_path)
        else:
            try:
                alias_path, alias_created = self._ensure_import_alias(model)
                logger.debug(
                    "Importing model via LM Studio: %s (mode=%s, dry_run=%s)",
                    alias_path,
                    link_mode,
                    dry_run,
                )
            except RuntimeError as exc:
                logger.debug("Failed to create import alias: %s", exc)
                return SyncResult(
                    model=model,
                    status="error",
                    message=str(exc),
                )
        try:
            import_result = self.lmstudio.import_model(
                str(alias_path),
                user_repo=model.user_repo,
                link_mode=link_mode,
                dry_run=dry_run,
            )
            logger.debug(
                "LM Studio import completed: %s", import_result.return_code
            )
        finally:
            if (
                dry_run
                and alias_created
                and alias_path.exists()
                and import_mode is not ImportMode.DIRECT
            ):
                logger.debug("Cleaning up dry-run alias: %s", alias_path)
                alias_path.unlink()
        record = SyncRecord(
            canonical_name=model.canonical_name,
            digest=model.model_digest,
            blob_path=model.blob_path,
            import_alias_path=alias_path,
            user_repo=model.user_repo,
            link_mode=link_mode,
            imported_at=datetime.now(tz=timezone.utc),
            import_command=import_result.command,
        )
        return SyncResult(
            model=model,
            status="dry-run" if dry_run else "synced",
            message=self._format_import_message(import_result),
            record=record,
        )
    def _ensure_import_alias(self, model: OllamaModel) -> tuple[Path, bool]:
        return SyncerAdapter._ensure_import_alias_static(
            model, self.config.import_staging_dir
        )
    @staticmethod
    def _is_currently_synced(model: OllamaModel, record: SyncRecord | None) -> bool:
        return SyncerAdapter._is_currently_synced_static(model, record)
    @staticmethod
    def _format_import_message(result: object) -> str:
        return SyncerAdapter._format_import_message_static(result)
class SyncerAdapter:
    @staticmethod
    def _ensure_import_alias_static(
        model: OllamaModel, staging_dir: Path
    ) -> tuple[Path, bool]:
        alias_path = staging_dir / model.import_filename
        if alias_path.exists():
            logger.debug("Import alias already exists: %s", alias_path)
            return alias_path, False
        if model.blob_path is None:
            raise RuntimeError(f"No blob path for model {model.canonical_name}")
        staging_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.link(model.blob_path, alias_path)
            logger.debug("Created hard link: %s -> %s", alias_path, model.blob_path)
            return alias_path, True
        except OSError as exc:
            raise RuntimeError(
                f"Failed to create import alias (hard link): {exc}"
            ) from exc
    @staticmethod
    def _is_currently_synced_static(model: OllamaModel, record: SyncRecord | None) -> bool:
        if record is None:
            return False
        if record.digest != model.model_digest:
            return False
        if record.link_mode is None:
            return False
        return True
    @staticmethod
    def _format_import_message_static(result: object) -> str:
        return "imported successfully"