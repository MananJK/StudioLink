from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class LinkMode(StrEnum):
    HARD_LINK = "hard-link"
    COPY = "copy"
    SYMBOLIC_LINK = "symbolic-link"

    @property
    def lms_flag(self) -> str:
        return {
            LinkMode.HARD_LINK: "--hard-link",
            LinkMode.COPY: "--copy",
            LinkMode.SYMBOLIC_LINK: "--symbolic-link",
        }[self]


class ImportMode(StrEnum):
    ALIAS = "alias"  # Use import aliases (hard links) - default
    DIRECT = "direct"  # Use Ollama blobs directly (no import)


class ModelReadiness(StrEnum):
    READY = "ready"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(slots=True, frozen=True)
class OllamaModel:
    canonical_name: str
    fully_qualified_name: str
    registry: str
    namespace: str
    repository: str
    tag: str
    manifest_path: Path
    model_digest: str | None
    blob_path: Path | None
    declared_size: int | None
    blob_size: int | None
    gguf_valid: bool
    issues: tuple[str, ...] = ()

    @property
    def readiness(self) -> ModelReadiness:
        if self.gguf_valid:
            return ModelReadiness.READY
        if any(
            "blob is missing from the Ollama blob store" in issue
            for issue in self.issues
        ):
            return ModelReadiness.STALE
        return ModelReadiness.INVALID

    @property
    def blob_present(self) -> bool:
        return self.blob_path is not None and self.blob_path.exists()

    @property
    def short_name(self) -> str:
        return f"{self.repository}:{self.tag}"

    @property
    def user_repo(self) -> str:
        repo_parts = []
        if self.registry != "registry.ollama.ai":
            repo_parts.append(self.registry.replace(".", "-"))
        if self.namespace != "library":
            repo_parts.append(self.namespace)
        repo_parts.append(self.repository.replace("/", "--"))
        return f"ollama/{'-'.join(repo_parts)}"

    @property
    def import_filename(self) -> str:
        raw = f"{self.canonical_name}-{(self.model_digest or 'unknown').replace(':', '-')[:5]}"
        safe = "".join(
            ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in raw
        )
        while "--" in safe:
            safe = safe.replace("--", "-")
        return f"{safe}.gguf"


@dataclass(slots=True, frozen=True)
class SyncRecord:
    canonical_name: str
    digest: str
    blob_path: Path
    import_alias_path: Path
    user_repo: str
    link_mode: LinkMode
    imported_at: datetime
    import_command: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, object]:
        return {
            "canonical_name": self.canonical_name,
            "digest": self.digest,
            "blob_path": str(self.blob_path),
            "import_alias_path": str(self.import_alias_path),
            "user_repo": self.user_repo,
            "link_mode": self.link_mode.value,
            "imported_at": self.imported_at.isoformat(),
            "import_command": list(self.import_command),
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "SyncRecord":
        return cls(
            canonical_name=str(payload["canonical_name"]),
            digest=str(payload["digest"]),
            blob_path=Path(str(payload["blob_path"])),
            import_alias_path=Path(str(payload["import_alias_path"])),
            user_repo=str(payload["user_repo"]),
            link_mode=LinkMode(str(payload["link_mode"])),
            imported_at=datetime.fromisoformat(str(payload["imported_at"])),
            import_command=tuple(
                str(item) for item in payload.get("import_command", [])
            ),
        )


@dataclass(slots=True, frozen=True)
class ImportResult:
    command: tuple[str, ...]
    stdout: str
    stderr: str
    return_code: int
    dry_run: bool = False


@dataclass(slots=True, frozen=True)
class SyncResult:
    model: OllamaModel
    status: str
    message: str
    record: SyncRecord | None = None


@dataclass(slots=True, frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    details: str
