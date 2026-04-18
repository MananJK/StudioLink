from __future__ import annotations

import subprocess
from typing import Any

from studiolink.config import StudioLinkConfig
from studiolink.models import ImportResult, LinkMode

DEFAULT_TIMEOUT = 60


class LMStudioError(Exception):
    """Raised when LM Studio CLI command fails."""

    def __init__(
        self, message: str, command: list[str], return_code: int, stderr: str
    ) -> None:
        super().__init__(message)
        self.command = command
        self.return_code = return_code
        self.stderr = stderr


class LMStudioAdapter:
    def __init__(self, config: StudioLinkConfig) -> None:
        self.config = config

    def get_version(self) -> str | None:
        try:
            result = self._run([str(self.config.lms_exe), "--version"], check=True)
            return result.stdout.strip() or None
        except subprocess.CalledProcessError as exc:
            raise LMStudioError(
                f"Failed to get LM Studio version: {exc.stderr}",
                exc.cmd,
                exc.returncode,
                exc.stderr,
            ) from exc

    def get_import_capabilities(self) -> set[LinkMode]:
        try:
            result = self._run(
                [str(self.config.lms_exe), "import", "--help"], check=True
            )
        except subprocess.CalledProcessError as exc:
            raise LMStudioError(
                f"Failed to get LM Studio import capabilities: {exc.stderr}",
                exc.cmd,
                exc.returncode,
                exc.stderr,
            ) from exc
        help_text = "\n".join(part for part in (result.stdout, result.stderr) if part)
        capabilities: set[LinkMode] = set()
        if "--hard-link" in help_text:
            capabilities.add(LinkMode.HARD_LINK)
        if "--copy" in help_text:
            capabilities.add(LinkMode.COPY)
        if "--symbolic-link" in help_text:
            capabilities.add(LinkMode.SYMBOLIC_LINK)
        return capabilities

    def import_model(
        self,
        source_path: str,
        *,
        user_repo: str,
        link_mode: LinkMode,
        dry_run: bool = False,
    ) -> ImportResult:
        command = [
            str(self.config.lms_exe),
            "import",
            source_path,
            "--yes",
            "--user-repo",
            user_repo,
            link_mode.lms_flag,
        ]
        if dry_run:
            command.append("--dry-run")

        try:
            result = self._run(command, check=True)
        except subprocess.CalledProcessError as exc:
            raise LMStudioError(
                f"LM Studio import failed for {source_path}: {exc.stderr}",
                exc.cmd,
                exc.returncode,
                exc.stderr,
            ) from exc
        return ImportResult(
            command=tuple(command),
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            dry_run=dry_run,
        )

    @staticmethod
    def _run(
        command: list[str], *, check: bool, timeout: int = DEFAULT_TIMEOUT
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
