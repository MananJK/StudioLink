from __future__ import annotations

import json
from pathlib import Path

from studiolink.config import StudioLinkConfig
from studiolink.models import OllamaModel


MODEL_MEDIA_TYPE = "application/vnd.ollama.image.model"
GGUF_MAGIC = b"GGUF"


class OllamaAdapter:
    def __init__(self, config: StudioLinkConfig) -> None:
        self.config = config

    def scan_models(self) -> list[OllamaModel]:
        manifests_dir = self.config.ollama_manifests_dir
        if not manifests_dir.exists():
            return []

        models: list[OllamaModel] = []
        for manifest_path in sorted(path for path in manifests_dir.rglob("*") if path.is_file()):
            model = self._parse_manifest(manifest_path)
            if model is not None:
                models.append(model)
        return models

    def _parse_manifest(self, manifest_path: Path) -> OllamaModel | None:
        try:
            relative_parts = manifest_path.relative_to(self.config.ollama_manifests_dir).parts
        except ValueError:
            return None

        if len(relative_parts) < 4:
            return None

        registry = relative_parts[0]
        namespace = relative_parts[1]
        repository = "/".join(relative_parts[2:-1])
        tag = relative_parts[-1]

        issues: list[str] = []
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"invalid manifest JSON: {exc}")
            manifest = {}

        model_layer = None
        for layer in manifest.get("layers", []):
            if isinstance(layer, dict) and layer.get("mediaType") == MODEL_MEDIA_TYPE:
                model_layer = layer
                break

        model_digest = None
        blob_path = None
        declared_size = None
        blob_size = None
        gguf_valid = False

        if model_layer is None:
            issues.append("missing Ollama model layer")
        else:
            model_digest = str(model_layer.get("digest", "")).strip() or None
            declared_size = self._as_int(model_layer.get("size"))
            if model_digest is None:
                issues.append("model layer is missing a digest")
            else:
                blob_path = self.config.ollama_blobs_dir / model_digest.replace(":", "-")
                if not blob_path.exists():
                    issues.append("model blob is missing from the Ollama blob store")
                else:
                    blob_size = blob_path.stat().st_size
                    if self._has_gguf_header(blob_path):
                        gguf_valid = True
                    else:
                        issues.append("blob does not start with GGUF magic bytes")

        canonical_name = self._canonical_name(registry, namespace, repository, tag)
        fully_qualified_name = f"{registry}/{namespace}/{repository}:{tag}"
        return OllamaModel(
            canonical_name=canonical_name,
            fully_qualified_name=fully_qualified_name,
            registry=registry,
            namespace=namespace,
            repository=repository,
            tag=tag,
            manifest_path=manifest_path,
            model_digest=model_digest,
            blob_path=blob_path,
            declared_size=declared_size,
            blob_size=blob_size,
            gguf_valid=gguf_valid,
            issues=tuple(issues),
        )

    @staticmethod
    def _as_int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _has_gguf_header(blob_path: Path) -> bool:
        with blob_path.open("rb") as handle:
            return handle.read(4) == GGUF_MAGIC

    @staticmethod
    def _canonical_name(registry: str, namespace: str, repository: str, tag: str) -> str:
        base_name = f"{repository}:{tag}" if namespace == "library" else f"{namespace}/{repository}:{tag}"
        if registry == "registry.ollama.ai":
            return base_name
        return f"{registry}/{base_name}"
