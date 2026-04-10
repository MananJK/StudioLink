# StudioLink

StudioLink is a Python CLI that lets LM Studio use models downloaded through Ollama.

For v1, StudioLink treats Ollama as the source of truth, discovers GGUF-backed models from Ollama manifests, and imports them into LM Studio via `lms import`, using hard links by default.

## Commands

```powershell
studiolink scan
studiolink sync deepseek-r1:8b
studiolink sync --all
studiolink status
studiolink doctor
```

## Design Notes

- `ollama_adapter` reads manifests and resolves GGUF blobs from the Ollama model store.
- `lmstudio_adapter` shells out to the public `lms` CLI rather than relying on LM Studio internals.
- StudioLink keeps a small local state file in `~/.studiolink/state.json` so `status` can report models previously synced by StudioLink.
- Imports use a managed `.gguf` alias inside `~/.studiolink/imports/` to keep LM Studio imports friendly even though Ollama stores blobs by digest.
