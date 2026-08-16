from conftest import (
    DIGEST_A,
    blob_filename,
    write_blob,
    write_manifest,
)

from studiolink.models import ModelReadiness
from studiolink.ollama_adapter import OllamaAdapter


def scan_one(config):
    models = OllamaAdapter(config).scan_models()
    assert len(models) == 1, f"expected one model, got {models}"
    return models[0]


class TestScanHappyPath:
    def test_finds_ready_model(self, make_config):
        config = make_config()
        write_manifest(config, repository="llama3", tag="1b", digest=DIGEST_A)
        write_blob(config, DIGEST_A)

        model = scan_one(config)

        assert model.canonical_name == "llama3:1b"
        assert model.readiness is ModelReadiness.READY
        assert model.blob_path == config.ollama_blobs_dir / blob_filename(DIGEST_A)
        assert model.blob_size == 12  # 4 header bytes + 8 padding
        assert model.declared_size == 1234
        assert model.issues == ()

    def test_declared_size_garbage_is_tolerated(self, make_config):
        config = make_config()
        write_manifest(
            config,
            digest=DIGEST_A,
            content={
                "layers": [
                    {
                        "mediaType": "application/vnd.ollama.image.model",
                        "digest": DIGEST_A,
                        "size": "not-a-number",
                    }
                ]
            },
        )
        write_blob(config, DIGEST_A)
        model = scan_one(config)
        assert model.declared_size is None
        assert model.readiness is ModelReadiness.READY


class TestReadinessProblems:
    def test_missing_blob_is_stale(self, make_config):
        config = make_config()
        write_manifest(config, digest=DIGEST_A)
        model = scan_one(config)
        assert model.readiness is ModelReadiness.STALE
        assert "model blob is missing from the Ollama blob store" in model.issues

    def test_bad_magic_is_invalid(self, make_config):
        config = make_config()
        write_manifest(config, digest=DIGEST_A)
        write_blob(config, DIGEST_A, gguf=False)
        model = scan_one(config)
        assert model.readiness is ModelReadiness.INVALID
        assert "blob does not start with GGUF magic bytes" in model.issues

    def test_missing_model_layer(self, make_config):
        config = make_config()
        write_manifest(config, content={"schemaVersion": 2, "layers": []})
        model = scan_one(config)
        assert model.readiness is ModelReadiness.INVALID
        assert "missing Ollama model layer" in model.issues


class TestMalformedManifests:
    def test_non_dict_json_is_invalid_not_crash(self, make_config):
        # Regression: a stray JSON array under manifests/ used to raise
        # AttributeError and kill the whole scan.
        config = make_config()
        write_manifest(config, content=[1, 2, 3])
        model = scan_one(config)
        assert model.readiness is ModelReadiness.INVALID
        assert "manifest is not a JSON object" in model.issues

    def test_invalid_json_is_invalid_not_crash(self, make_config):
        config = make_config()
        write_manifest(config, raw_text="this is not json")
        model = scan_one(config)
        assert model.readiness is ModelReadiness.INVALID
        assert any("invalid manifest JSON" in issue for issue in model.issues)

    def test_layer_without_digest(self, make_config):
        config = make_config()
        write_manifest(
            config,
            content={
                "layers": [
                    {"mediaType": "application/vnd.ollama.image.model", "size": 5}
                ]
            },
        )
        model = scan_one(config)
        assert model.readiness is ModelReadiness.INVALID
        assert "model layer is missing a digest" in model.issues


class TestManifestLayout:
    def test_missing_manifests_dir_returns_empty(self, make_config):
        assert OllamaAdapter(make_config()).scan_models() == []

    def test_file_with_too_few_path_parts_skipped(self, make_config):
        config = make_config()
        stray = config.ollama_manifests_dir / "registry.ollama.ai" / "library"
        stray.mkdir(parents=True)
        (stray / "stray-file").write_text("{}", encoding="utf-8")
        assert OllamaAdapter(config).scan_models() == []

    def test_nested_repository_path(self, make_config):
        config = make_config()
        write_manifest(config, repository="team/model", tag="2b", digest=DIGEST_A)
        write_blob(config, DIGEST_A)
        model = scan_one(config)
        assert model.repository == "team/model"
        assert model.canonical_name == "team/model:2b"

    def test_custom_registry_and_namespace(self, make_config):
        config = make_config()
        write_manifest(
            config,
            registry="ghcr.io",
            namespace="marella",
            repository="gemma",
            digest=DIGEST_A,
        )
        write_blob(config, DIGEST_A)
        model = scan_one(config)
        assert model.canonical_name == "ghcr.io/marella/gemma:1b"
        assert model.fully_qualified_name == "ghcr.io/marella/gemma:1b"

    def test_multiple_models_sorted_by_path(self, make_config):
        config = make_config()
        write_manifest(config, repository="zeta", tag="1b", digest=DIGEST_A)
        write_blob(config, DIGEST_A)
        write_manifest(config, repository="alpha", tag="1b", digest=DIGEST_A)
        models = OllamaAdapter(config).scan_models()
        assert [m.repository for m in models] == ["alpha", "zeta"]
