"""Controlled local Python execution for the single-user version."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class SandboxPolicyError(RuntimeError):
    pass


@dataclass
class ExecResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: list[str] = field(default_factory=list)
    script_path: str | None = None


class PythonSandbox:
    banned_fragments = (
        "os.system",
        "subprocess",
        "shutil.rmtree",
        "requests.",
        "urllib.",
        "socket.",
        "httpx.",
    )

    def __init__(
        self,
        timeout: int = 60,
        max_memory_mb: int = 1024,
        max_stdout_chars: int = 20000,
    ):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.max_stdout_chars = max_stdout_chars

    def execute(
        self,
        code: str,
        workdir: str | Path,
        step_id: str,
        attempt: int = 0,
        timeout: int | None = None,
    ) -> ExecResult:
        workdir = Path(workdir)
        timeout = timeout or self.timeout
        try:
            self._static_check(code)
        except SandboxPolicyError as exc:
            return ExecResult(success=False, stderr=str(exc), output_files=[])

        scripts_dir = workdir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / f"{step_id}_attempt_{attempt}.py"
        script_path.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._build_env(workdir),
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                success=False,
                stderr=f"执行超时（{timeout}秒）",
                output_files=[],
                script_path=str(script_path),
            )

        return ExecResult(
            success=result.returncode == 0,
            stdout=result.stdout[: self.max_stdout_chars],
            stderr=result.stderr[-self.max_stdout_chars :],
            output_files=self._list_output_files(workdir),
            script_path=str(script_path),
        )

    def _static_check(self, code: str) -> None:
        hits = [fragment for fragment in self.banned_fragments if fragment in code]
        if hits:
            raise SandboxPolicyError(f"代码包含不允许的调用: {hits}")

    def _build_env(self, workdir: Path) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH"}
        }
        env.update(
            {
                "PYTHONPATH": str(workdir),
                "MPLBACKEND": "Agg",
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def _list_output_files(self, workdir: Path) -> list[str]:
        output_dir = workdir / "output"
        if not output_dir.exists():
            return []
        return [
            str(path.relative_to(workdir))
            for path in output_dir.iterdir()
            if path.is_file()
        ]
