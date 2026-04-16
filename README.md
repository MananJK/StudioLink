# StudioLink

**Sync Ollama-downloaded GGUF models into LM Studio.**

StudioLink is a Python CLI tool that bridges Ollama and LM Studio. It treats Ollama as the source of truth, discovers GGUF-backed models from Ollama manifests, and imports them into LM Studio via the `lms` CLI—using hard links by default to save disk space.

## Features

- 🔍 **Scan** - Discover all GGUF models available in your Ollama library
- 🔄 **Sync** - Import models into LM Studio with one command
- 📊 **Status** - Track which models are synced and their current state
- 🩺 **Doctor** - Verify prerequisites and diagnose issues
- 🔗 **Smart linking** - Uses hard links by default, falls back to copy when needed
- 💾 **State tracking** - Remembers what's been synced to avoid re-importing

## Prerequisites

Before using StudioLink, ensure you have:

1. **Ollama** installed and available at `~/.ollama/models/`
2. **LM Studio** with the `lms` CLI installed at `~/.lmstudio/bin/lms.exe`
3. **Python 3.12+**

## Installation

```powershell
# Clone the repository
git clone https://github.com/MananJK/StudioLink.git
cd StudioLink

# Install in editable mode
pip install -e .
```

## Quick Start

```powershell
# Scan for available models
sdl scan

# Import a specific model
sdl sync <modelname>

# Import all discovered models
sdl sync --all

# Check sync status
sdl status

# Verify everything is set up correctly
sdl doctor
```

## Commands

### `sdl scan`
Discover all GGUF-backed Ollama models available for import.

```powershell
# Basic scan
sdl scan

# Output as JSON
sdl scan --json

# Verbose output (debug logging)
sdl -v scan
```

**Output:**
```
Discovered 3 model(s):
- <modelname> [ready]
  blob: C:\Users\...\ollama\models\blobs\sha256-...
- <modelname2> [stale]
  blob: C:\Users\...\ollama\models\blobs\sha256-...
  issues: model blob is missing from the Ollama blob store
```

### `sdl sync`
Import one or more models into LM Studio.

```powershell
# Import specific model(s)
sdl sync <modelname>
sdl sync <model1> <model2> <model3>

# Import all discovered models
sdl sync --all

# Preview without making changes (dry run)
sdl sync <modelname> --dry-run

# Use a specific link mode
sdl sync <modelname> --hard-link
sdl sync <modelname> --copy
sdl sync <modelname> --symbolic-link

# Verbose output
sdl -v sync --all
```

**Options:**
- `--all` - Sync every discovered model
- `--dry-run` - Preview the import without making changes
- `--copy` - Use copy mode instead of hard links
- `--hard-link` - Force hard link mode (default)
- `--symbolic-link` - Use symbolic links

### `sdl status`
Show discovered models and their sync state.

```powershell
sdl status
sdl status --json
sdl -v status
```

**Output:**
```
Discovered 3 model(s); 1 tracked as synced.
- <modelname>: synced
  imported: 2026-04-12T10:30:00+00:00
- <modelname2>: stale
  issues: model blob is missing from the Ollama blob store
- <modelname3>: pending
```

### `sdl doctor`
Check local StudioLink prerequisites and diagnose issues.

```powershell
sdl doctor
sdl doctor --json
```

**Checks include:**
- Ollama executable exists
- LM Studio CLI (`lms`) exists
- Ollama manifests and blobs directories exist
- LM Studio models directory exists
- Hard-link volume compatibility (same drive)
- Discovered Ollama models
- Blob presence validation
- GGUF header validation

### `sdl help`
Show all available commands and their descriptions.

```powershell
sdl help
```

## Global Options

All commands support these global options:

- `-v, --verbose` - Enable verbose output (debug logging)
- `--version` - Show version information
- `--help` - Show help for the specific command

```powershell
# Examples
sdl -v scan              # Scan with debug logging
sdl sync --help          # Show help for sync command
sdl --version            # Show version
```

## Model Readiness States

When scanning or checking status, models can have these states:

| State | Description | Action Required |
|-------|-------------|-----------------|
| **ready** | Model blob exists and has valid GGUF header | Ready to sync |
| **stale** | Manifest exists but blob is missing | Run `ollama pull <model>` to restore |
| **invalid** | Blob exists but missing GGUF magic bytes | Model may be corrupted |
| **synced** | Already imported into LM Studio | No action needed |
| **pending** | Ready but not yet synced | Run `sdl sync` |

## Configuration

StudioLink uses the following default paths (Windows):

| Setting | Default Path | Environment Variable |
|---------|--------------|---------------------|
| Ollama executable | `~\AppData\Local\Programs\Ollama\ollama.exe` | `STUDIOLINK_OLLAMA_EXE` |
| LM Studio CLI | `~\.lmstudio\bin\lms.exe` | `STUDIOLINK_LMS_EXE` |
| Ollama models | `~\.ollama\models` | `STUDIOLINK_OLLAMA_MODELS_DIR` |
| LM Studio models | `~\.lmstudio\models` | `STUDIOLINK_LMSTUDIO_MODELS_DIR` |
| State directory | `~\.sdl` | `STUDIOLINK_STATE_DIR` |

## How It Works

1. **Scanning** - Reads Ollama manifest files from `~/.ollama/models/manifests/` to discover models
2. **Blob Resolution** - Locates GGUF blobs in `~/.ollama/models/blobs/` by digest
3. **Validation** - Verifies blobs start with GGUF magic bytes
4. **Import Aliases** - Creates human-readable `.gguf` aliases in `~/.sdl/imports/`
5. **LM Studio Import** - Uses `lms import` CLI to import models
6. **State Tracking** - Saves sync records to `~/.sdl/state.json`

## Troubleshooting

### "model blob is missing from the Ollama blob store"
The model manifest exists but the actual blob file has been deleted or purged by Ollama. Re-download it:
```powershell
ollama pull <model-name>
```

### Hard link fails (cross-volume)
StudioLink automatically falls back to copy mode if hard links fail (e.g., Ollama and StudioLink state are on different drives). Use `--verbose` to see the fallback in action.

### LM Studio import fails
Run `sdl doctor` to verify:
- LM Studio is installed
- `lms` CLI is in PATH
- Import directories are writable

## Design Notes

- **Ollama as source of truth** - StudioLink never modifies Ollama's model store
- **Hard links by default** - Space-efficient, creates references rather than copies
- **Cross-volume fallback** - Automatically copies when hard links aren't possible
- **State persistence** - Tracks imports to avoid redundant operations
- **CLI-only** - No GUI, designed for automation and scripting

## License

MIT License - See [LICENSE](LICENSE) for details.
