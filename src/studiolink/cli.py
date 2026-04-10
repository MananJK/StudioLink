from __future__ import annotations

import argparse
import json
from datetime import timezone

from studiolink import __version__
from studiolink.models import DoctorCheck, LinkMode, SyncResult
from studiolink.service import StatusEntry, StudioLinkService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studiolink",
        description="Sync Ollama-downloaded GGUF models into LM Studio.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Discover GGUF-backed Ollama models.")
    scan_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    scan_parser.set_defaults(func=run_scan)

    sync_parser = subparsers.add_parser("sync", help="Import one or more models into LM Studio.")
    sync_parser.add_argument("models", nargs="*", help="Model names from `studiolink scan`.")
    sync_parser.add_argument("--all", action="store_true", help="Sync every discovered model.")
    sync_parser.add_argument("--dry-run", action="store_true", help="Preview the import command without changing state.")
    sync_parser.add_argument("--copy", action="store_true", help="Use LM Studio copy mode.")
    sync_parser.add_argument("--hard-link", action="store_true", help="Use LM Studio hard-link mode.")
    sync_parser.add_argument("--symbolic-link", action="store_true", help="Use LM Studio symbolic-link mode.")
    sync_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    sync_parser.set_defaults(func=run_sync)

    status_parser = subparsers.add_parser("status", help="Show discovered models and sync state.")
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    status_parser.set_defaults(func=run_status)

    doctor_parser = subparsers.add_parser("doctor", help="Check local StudioLink prerequisites.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    doctor_parser.set_defaults(func=run_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = StudioLinkService()
    try:
        return int(args.func(args, service))
    except ValueError as exc:
        parser.error(str(exc))
        return 2


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
        state = "ready" if model.gguf_valid else "invalid"
        print(f"- {model.canonical_name} [{state}]")
        print(f"  blob: {model.blob_path or 'missing'}")
        if model.issues:
            print(f"  issues: {'; '.join(model.issues)}")
    return 0


def run_sync(args: argparse.Namespace, service: StudioLinkService) -> int:
    mode = _resolve_link_mode(args)
    results = service.sync(
        model_names=args.models,
        sync_all=bool(args.all),
        link_mode=mode,
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
        status = "synced" if entry.synced else "pending"
        print(f"- {entry.model.canonical_name}: {status}")
        if entry.sync_record is not None:
            imported_at = entry.sync_record.imported_at.astimezone(timezone.utc).isoformat()
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
        "blob_path": str(getattr(model, "blob_path")) if getattr(model, "blob_path") else None,
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
        "sync_record": None if entry.sync_record is None else entry.sync_record.to_json(),
    }


def _doctor_check_to_json(check: DoctorCheck) -> dict[str, object]:
    return {
        "name": check.name,
        "ok": check.ok,
        "details": check.details,
    }
