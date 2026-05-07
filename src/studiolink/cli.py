from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timezone

from studiolink import __version__
from studiolink.lmstudio_adapter import LMStudioError
from studiolink.models import DoctorCheck, ImportMode, LinkMode, SyncResult
from studiolink.service import StatusEntry, StudioLinkService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdl",
        usage="sdl [-v] [--version] [--help] <command> [<args>]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "-v", action="store_true", help="Enable verbose output (debug logging)."
    )
    parser.add_argument(
        "--version", action="store_true", help="Show version information."
    )
    parser.add_argument(
        "--help", action="store_true", help="Show this help message and exit."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="Discover GGUF-backed Ollama models."
    )
    scan_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    scan_parser.set_defaults(func=run_scan)

    sync_parser = subparsers.add_parser(
        "sync", help="Import one or more models into LM Studio."
    )
    sync_parser.add_argument("models", nargs="*", help="Model names from `sdl scan`.")
    sync_parser.add_argument(
        "--all", action="store_true", help="Sync every discovered model."
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the import command without changing state.",
    )
    sync_parser.add_argument(
        "--copy", action="store_true", help="Use LM Studio copy mode."
    )
    sync_parser.add_argument(
        "--hard-link", action="store_true", help="Use LM Studio hard-link mode."
    )
    sync_parser.add_argument(
        "--symbolic-link", action="store_true", help="Use LM Studio symbolic-link mode."
    )
    sync_parser.add_argument(
        "--direct",
        action="store_true",
        help="Use Ollama blobs directly (skip import, no extra storage).",
    )
    sync_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    sync_parser.set_defaults(func=run_sync)

    status_parser = subparsers.add_parser(
        "status", help="Show discovered models and sync state."
    )
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    status_parser.set_defaults(func=run_status)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Check local StudioLink prerequisites."
    )
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    doctor_parser.set_defaults(func=run_doctor)
    return parser


def _preparse_args(argv: list[str] | None) -> tuple[argparse.Namespace | None, bool]:
    """Pre-parse args to handle help/version before subparsers."""
    parser = argparse.ArgumentParser(
        prog="sdl",
        usage="sdl [-v] [--version] [--help] <command> [<args>]",
        add_help=False,
    )
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--help", action="store_true")
    parser.add_argument("-v", action="store_true")
    parser.add_argument("command", nargs="?", choices=["scan", "sync", "status", "doctor"])

    import io
    from contextlib import redirect_stderr

    try:
        with redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
    except SystemExit:
        return None, True

    if args.help or args.version:
        return args, False

    return args, True


def main(argv: list[str] | None = None) -> int:
    preparsed, should_continue = _preparse_args(argv)

    if preparsed is None and not should_continue:
        build_parser().print_help()
        return 0

    if preparsed and (preparsed.help or preparsed.version):
        parser = build_parser()
        if preparsed.version:
            print(f"StudioLink {__version__}")
            return 0
        if preparsed.help:
            build_parser().print_help()
            return 0

    parser = build_parser()

    import io
    from contextlib import redirect_stderr

    try:
        with redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
    except SystemExit:
        print(
            "Error: Invalid command. Use 'sdl --help' for available commands.",
            file=sys.stderr,
        )
        return 1

    verbose = (preparsed and getattr(preparsed, "v", False)) or (args and getattr(args, "verbose", False))
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
        logging.getLogger("studiolink").setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
        logging.getLogger("studiolink").setLevel(logging.WARNING)
    service = StudioLinkService()
    logging.debug("Configuration loaded:")
    logging.debug("  Ollama manifests: %s", service.config.ollama_manifests_dir)
    logging.debug("  Ollama blobs: %s", service.config.ollama_blobs_dir)
    logging.debug("  LM Studio models: %s", service.config.lmstudio_models_dir)
    logging.debug("  State file: %s", service.config.state_file)
    try:
        return int(args.func(args, service))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except LMStudioError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_scan(args: argparse.Namespace, service: StudioLinkService) -> int:
    models = service.scan()
    if args.json:
        print(json.dumps([_model_to_json(model) for model in models], indent=2))
        return 0

    if not models:
        print("No Ollama manifests were discovered.")
        return 0

    print(f"Discovered {len(models)} model(s):")
    for model in models:
        print(f"- {model.canonical_name} [{model.readiness.value}]")
        print(f"  blob: {model.blob_path or 'missing'}")
        if model.issues:
            print(f"  issues: {'; '.join(model.issues)}")
    return 0


def run_sync(args: argparse.Namespace, service: StudioLinkService) -> int:
    mode = _resolve_link_mode(args)
    import_mode = ImportMode.DIRECT if args.direct else ImportMode.ALIAS
    results = service.sync(
        model_names=args.models,
        sync_all=bool(args.all),
        link_mode=mode,
        import_mode=import_mode,
        dry_run=bool(args.dry_run),
    )
    if args.json:
        print(json.dumps([_sync_result_to_json(item) for item in results], indent=2))
        return 0 if all(item.status != "error" for item in results) else 1

    for item in results:
        print(f"- {item.model.canonical_name}: {item.status}")
        print(f"  {item.message}")
    return 0 if all(item.status != "error" for item in results) else 1


def run_status(args: argparse.Namespace, service: StudioLinkService) -> int:
    entries = service.status()
    if args.json:
        print(json.dumps([_status_entry_to_json(entry) for entry in entries], indent=2))
        return 0

    if not entries:
        print("No Ollama manifests were discovered.")
        return 0

    synced = sum(1 for entry in entries if entry.synced)
    print(f"Discovered {len(entries)} model(s); {synced} tracked as synced.")
    for entry in entries:
        print(f"- {entry.model.canonical_name}: {entry.display_status}")
        if entry.sync_record is not None:
            imported_at = entry.sync_record.imported_at.astimezone(
                timezone.utc
            ).isoformat()
            print(f"  imported: {imported_at}")
        if entry.model.issues:
            print(f"  issues: {'; '.join(entry.model.issues)}")
    return 0


def run_doctor(args: argparse.Namespace, service: StudioLinkService) -> int:
    checks = service.doctor()
    if args.json:
        print(json.dumps([_doctor_check_to_json(check) for check in checks], indent=2))
        return 0 if all(check.ok for check in checks) else 1

    for check in checks:
        prefix = "OK" if check.ok else "FAIL"
        print(f"- {prefix}: {check.name} -> {check.details}")
    return 0 if all(check.ok for check in checks) else 1


def run_help(args: argparse.Namespace, service: StudioLinkService) -> int:
    help_text = """StudioLink - Sync Ollama-downloaded GGUF models into LM Studio.

Available Commands:

  scan              Discover GGUF-backed Ollama models.
                    Usage: sdl scan [--json] [-v]

  sync              Import one or more models into LM Studio.
                    Usage: sdl sync <model> [<model>...] [--copy|--hard-link|--symbolic-link] [--dry-run] [-v]
                           sdl sync --all [--copy|--hard-link|--symbolic-link] [--dry-run] [-v]

  status            Show discovered models and sync state.
                    Usage: sdl status [--json] [-v]

  doctor            Check local StudioLink prerequisites.
                    Usage: sdl doctor [--json] [-v]

  help              Show this help message.

Global Options:

  -v, --verbose     Enable verbose output (debug logging).
  --version         Show version information.
  --help            Show help for a specific command.

Examples:

  sdl scan                       # List all available models
  sdl -v scan                    # Scan with debug output
  sdl sync <modelname>           # Import a specific model
  sdl sync --all                 # Import all discovered models
  sdl status                     # Check sync status
  sdl doctor                     # Verify prerequisites

For more help on a specific command:
  sdl <command> --help
"""
    print(help_text)
    return 0


def _resolve_link_mode(args: argparse.Namespace) -> LinkMode | None:
    selected = [
        mode
        for flag, mode in (
            (args.copy, LinkMode.COPY),
            (args.hard_link, LinkMode.HARD_LINK),
            (args.symbolic_link, LinkMode.SYMBOLIC_LINK),
        )
        if flag
    ]
    if len(selected) > 1:
        raise ValueError("choose only one of --copy, --hard-link, or --symbolic-link")
    return selected[0] if selected else None


def _model_to_json(model: object) -> dict[str, object]:
    return {
        "canonical_name": getattr(model, "canonical_name"),
        "fully_qualified_name": getattr(model, "fully_qualified_name"),
        "blob_path": str(getattr(model, "blob_path"))
        if getattr(model, "blob_path")
        else None,
        "readiness": getattr(model, "readiness").value,
        "gguf_valid": getattr(model, "gguf_valid"),
        "issues": list(getattr(model, "issues")),
        "user_repo": getattr(model, "user_repo"),
    }


def _sync_result_to_json(result: SyncResult) -> dict[str, object]:
    return {
        "model": result.model.canonical_name,
        "status": result.status,
        "message": result.message,
        "record": None if result.record is None else result.record.to_json(),
    }


def _status_entry_to_json(entry: StatusEntry) -> dict[str, object]:
    return {
        "model": _model_to_json(entry.model),
        "synced": entry.synced,
        "status": entry.display_status,
        "sync_record": None
        if entry.sync_record is None
        else entry.sync_record.to_json(),
    }


def _doctor_check_to_json(check: DoctorCheck) -> dict[str, object]:
    return {
        "name": check.name,
        "ok": check.ok,
        "details": check.details,
    }
