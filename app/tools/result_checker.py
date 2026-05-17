"""Deterministic checks for generated analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckItem:
    name: str
    status: str
    message: str = ""


@dataclass
class CheckResult:
    step_id: str
    status: str
    checks: list[CheckItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def to_prompt_text(self) -> str:
        lines = [f"结果校验状态: {self.status}"]
        for check in self.checks:
            lines.append(f"- {check.name}: {check.status} {check.message}".strip())
        return "\n".join(lines)


class ResultChecker:
    def validate(self, step: Any, exec_result: Any, context: Any, workspace: Any) -> CheckResult:
        checks = [
            self._check_process_success(exec_result),
            self._check_stdout_not_empty(step, exec_result),
            self._check_expected_outputs(step, workspace),
        ]
        failed = any(check.status == "failed" for check in checks)
        warnings = [check.message for check in checks if check.status == "warning"]
        return CheckResult(
            step_id=step.id,
            status="failed" if failed else "passed",
            checks=checks,
            warnings=warnings,
        )

    def _check_process_success(self, exec_result: Any) -> CheckItem:
        if getattr(exec_result, "success", False):
            return CheckItem("process_success", "passed")
        return CheckItem("process_success", "failed", getattr(exec_result, "stderr", ""))

    def _check_stdout_not_empty(self, step: Any, exec_result: Any) -> CheckItem:
        if getattr(exec_result, "stdout", "").strip():
            return CheckItem("stdout_not_empty", "passed")
        if getattr(step, "expected_outputs", None):
            return CheckItem("stdout_not_empty", "warning", "stdout 为空，仅依赖输出文件")
        return CheckItem("stdout_not_empty", "failed", "没有摘要输出，Reporter 无法可靠引用结果")

    def _check_expected_outputs(self, step: Any, workspace: Any) -> CheckItem:
        expected = getattr(step, "expected_outputs", []) or []
        if not expected:
            return CheckItem("expected_outputs", "passed")
        missing = []
        output_files = {item.get("path") or item.get("name") for item in workspace.list_files()}
        for item in expected:
            path = item.get("path") or item.get("name")
            if path and path not in output_files and not Path(workspace.path, path).exists():
                missing.append(path)
        if missing:
            return CheckItem("expected_outputs", "failed", f"缺少预期产物: {missing}")
        return CheckItem("expected_outputs", "passed")
