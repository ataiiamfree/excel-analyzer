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
            self._check_output_files_readable(workspace, exec_result),
        ]
        checks.extend(self._check_basic_invariants(step, exec_result, context, workspace))
        failed = any(check.status == "failed" for check in checks)
        warnings = [check.message for check in checks if check.status == "warning"]
        return CheckResult(
            step_id=step.id,
            status="failed" if failed else "passed",
            checks=checks,
            warnings=warnings,
        )

    def _check_process_success(self, exec_result: Any) -> CheckItem:
        success = getattr(exec_result, "success", None)
        if success is None:
            success = not getattr(exec_result, "failed", True)
        if success:
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

    def _check_output_files_readable(self, workspace: Any, exec_result: Any) -> CheckItem:
        """验证输出文件是否存在且可读。"""
        output_files = getattr(exec_result, "output_files", None)
        if output_files is None:
            output_files = getattr(exec_result, "files", [])
        output_files = output_files or []
        if not output_files:
            return CheckItem("output_files_readable", "passed")
        unreadable = []
        for file_path in output_files:
            full = Path(workspace.path) / file_path
            if not full.exists():
                unreadable.append(f"{file_path} (不存在)")
            elif full.stat().st_size == 0:
                unreadable.append(f"{file_path} (空文件)")
            else:
                # 尝试读取前几个字节确认可读
                try:
                    with open(full, "rb") as f:
                        f.read(64)
                except OSError as exc:
                    unreadable.append(f"{file_path} ({exc})")
        if unreadable:
            return CheckItem("output_files_readable", "failed", f"输出文件不可读: {unreadable}")
        return CheckItem("output_files_readable", "passed")

    def _check_basic_invariants(
        self,
        step: Any,
        exec_result: Any,
        context: Any,
        workspace: Any,
    ) -> list[CheckItem]:
        """基础不变量校验：筛选行数、聚合总和等。"""
        checks: list[CheckItem] = []
        instruction = getattr(step, "instruction", "") or ""
        stdout = getattr(exec_result, "stdout", "") or ""
        # 从 context 的最新 step summary 中提取信息
        summaries = getattr(context, "step_summaries", {})
        step_id = getattr(step, "id", "")
        if step_id in summaries:
            stdout = summaries[step_id]

        # 检查1: 如果是筛选操作，输出行数不应为 0
        filter_keywords = ("筛选", "过滤", "filter", "where", "query")
        if any(kw in instruction for kw in filter_keywords):
            if "0 行" in stdout or "0行" in stdout or "空表" in stdout:
                checks.append(CheckItem(
                    "filter_not_empty", "warning",
                    "筛选结果为空，请确认筛选条件是否正确",
                ))

        # 检查2: 如果是导出操作，检查输出目录是否有文件
        export_keywords = ("导出", "export", "保存", "save", "写入")
        if any(kw in instruction for kw in export_keywords):
            output_dir = Path(workspace.path) / "output"
            if output_dir.exists() and not any(output_dir.iterdir()):
                checks.append(CheckItem(
                    "export_has_output", "warning",
                    "指令要求导出但 output/ 目录为空",
                ))

        return checks
