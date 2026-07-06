"""Controlled local Python execution for the single-user version."""

from __future__ import annotations

import ast
import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
        "__import__",
        "importlib",
        "compile(",
    )
    # 需要 AST 级检查的危险调用
    _ast_banned_calls = {"eval", "exec", "globals", "locals", "getattr", "setattr", "delattr"}

    def __init__(
        self,
        timeout: int = 60,
        max_memory_mb: int = 1024,
        max_stdout_chars: int = 20000,
        python_executable: str | None = None,
    ):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.max_stdout_chars = max_stdout_chars
        self.python_executable = python_executable or sys.executable

    def execute(
        self,
        code: str,
        workdir: str | Path,
        step_id: str,
        attempt: int = 0,
        timeout: int | None = None,
    ) -> ExecResult:
        workdir = Path(workdir).resolve()
        timeout = timeout or self.timeout
        try:
            self._static_check(code)
        except SandboxPolicyError as exc:
            return ExecResult(success=False, stderr=str(exc), output_files=[])

        scripts_dir = workdir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = (scripts_dir / f"{step_id}_attempt_{attempt}.py").resolve()
        script_path.write_text(code, encoding="utf-8")
        logger.info("沙箱执行: %s (代码 %d chars, timeout=%ds)", script_path.name, len(code), timeout)

        try:
            preexec = self._limit_resources if platform.system() != "Windows" else None
            result = subprocess.run(
                [self.python_executable, str(script_path)],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._build_env(workdir),
                preexec_fn=preexec,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                success=False,
                stderr=f"执行超时（{timeout}秒）",
                output_files=[],
                script_path=str(script_path),
            )

        exec_result = ExecResult(
            success=result.returncode == 0,
            stdout=self._truncate_stdout(result.stdout),
            stderr=result.stderr[-self.max_stdout_chars :],
            output_files=self._list_output_files(workdir),
            script_path=str(script_path),
        )
        if exec_result.success:
            logger.info("沙箱执行成功, stdout=%d chars, 产出文件=%s",
                        len(exec_result.stdout), exec_result.output_files or "无")
        else:
            logger.warning("沙箱执行失败 (returncode=%d), stderr=%s",
                           result.returncode, exec_result.stderr[:300])
        return exec_result

    def _truncate_stdout(self, stdout: str) -> str:
        if len(stdout) <= self.max_stdout_chars:
            return stdout
        if self.max_stdout_chars <= 0:
            return ""

        marker = "\n... [stdout truncated] ...\n"
        available = self.max_stdout_chars - len(marker)
        if available <= 0:
            return stdout[-self.max_stdout_chars :]

        head_chars = available // 2
        tail_chars = available - head_chars
        omitted = len(stdout) - head_chars - tail_chars
        marker = f"\n... [stdout truncated: omitted {omitted} chars] ...\n"
        available = self.max_stdout_chars - len(marker)
        if available <= 0:
            return stdout[-self.max_stdout_chars :]

        head_chars = available // 2
        tail_chars = available - head_chars
        omitted = len(stdout) - head_chars - tail_chars
        marker = f"\n... [stdout truncated: omitted {omitted} chars] ...\n"
        return stdout[:head_chars] + marker + stdout[-tail_chars:]

    def _static_check(self, code: str) -> None:
        # 1. 字符串片段快检
        hits = [fragment for fragment in self.banned_fragments if fragment in code]
        if hits:
            raise SandboxPolicyError(f"代码包含不允许的调用: {hits}")

        # 2. 禁止绝对路径 open
        if 'open("/' in code or "open('/" in code:
            raise SandboxPolicyError("禁止以绝对路径打开文件")

        # 3. AST 级检查：捕获 eval()/exec() 等无法通过字符串片段可靠检测的调用
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return  # 语法错误会在执行时报错，不在此拦截
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self._ast_banned_calls:
                    raise SandboxPolicyError(f"禁止调用 {node.func.id}()")

    def _build_env(self, workdir: Path) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH"}
        }
        mpl_config_dir = str(Path(__file__).resolve().parent / "mpl_config")
        env.update(
            {
                "PYTHONPATH": str(workdir),
                "MPLBACKEND": "Agg",
                "MPLCONFIGDIR": mpl_config_dir,
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def _limit_resources(self) -> None:
        """preexec_fn: 在子进程启动前限制内存。"""
        try:
            import resource
            mem_bytes = self.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            # macOS 可能不支持 RLIMIT_AS，降级跳过
            pass

    def _list_output_files(self, workdir: Path) -> list[str]:
        output_dir = workdir / "output"
        if not output_dir.exists():
            return []
        return [
            str(path.relative_to(workdir))
            for path in output_dir.iterdir()
            if path.is_file()
        ]
