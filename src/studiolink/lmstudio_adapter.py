from __future__ import annotations

import subprocess

from studiolink.config import StudioLinkConfig
from studiolink.models import ImportResult, LinkMode


class LMStudioAdapter:
    def __init__(self, config: StudioLinkConfig) -> None:
        self.config = config

    def get_version(self) -> str | None:
        result = self._run([str(self.config.lms_exe), "--version"], check=False)
        text = (result.stdout or result.stderr).strip()
        return text or None

    def get_import_capabilities(self) -> set[LinkMode]:
        result = self._run([str(self.config.lms_exe), "import", "--help"], check=False)
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

        result = self._run(command, check=True)
        return ImportResult(
            command=tuple(command),
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            dry_run=dry_run,
        )

    @staticmethod
    def _run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=check,
        )
