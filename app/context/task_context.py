"""Bounded task context used to assemble short, independent prompts."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import re
from typing import Any

from app.agent.plan import ExecutionPlan


BUDGET_PRESETS: dict[str, dict[str, int]] = {
    "standard": {
        "max_prompt_tokens": 4000,
        "step_summaries": 1000,
        "max_summary_per_step": 300,
        "max_findings": 10,
        "workspace_files": 200,
    },
    "generous": {
        "max_prompt_tokens": 16000,
        "step_summaries": 4000,
        "max_summary_per_step": 800,
        "max_findings": 20,
        "workspace_files": 400,
    },
    "deepseek": {
        "max_prompt_tokens": 32000,
        "step_summaries": 8000,
        "max_summary_per_step": 1500,
        "max_findings": 30,
        "workspace_files": 800,
    },
}


@dataclass
class TaskContext:
    task_id: str
    user_query: str
    workbook_manifest: dict[str, Any]
    data_profile: dict[str, Any]
    budget_preset: str = "deepseek"
    plan: ExecutionPlan | None = None
    selected_skill: str = "spreadsheet_analysis"
    skill_instructions: str = ""
    step_summaries: OrderedDict[str, str] = field(default_factory=OrderedDict)
    key_findings: list[str] = field(default_factory=list)
    final_answers: OrderedDict[str, str] = field(default_factory=OrderedDict)
    workspace_files: list[dict[str, Any]] = field(default_factory=list)
    artifact_manifest: list[dict[str, Any]] = field(default_factory=list)
    quality_checks: list[Any] = field(default_factory=list)
    code_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def budget(self) -> dict[str, int]:
        return BUDGET_PRESETS.get(self.budget_preset, BUDGET_PRESETS["generous"])

    def add_step_summary(self, step_id: str, stdout: str, step_desc: str) -> None:
        summary = self._extract_summary(stdout, self.budget["max_summary_per_step"])
        self.step_summaries[step_id] = f"{step_desc}: {summary}".strip()
        final_answer = self._extract_final_answer(stdout)
        if final_answer:
            self.final_answers[step_id] = final_answer
        findings = self._extract_findings(stdout)
        self.key_findings.extend(findings)
        self.key_findings = self.key_findings[-self.budget["max_findings"] :]
        self.compress_oldest_summaries()

    def update_workspace_files(self, files: list[dict[str, Any]]) -> None:
        self.workspace_files = files

    def update_artifacts(self, artifacts: list[dict[str, Any]]) -> None:
        self.artifact_manifest = artifacts

    def compress_oldest_summaries(self) -> bool:
        if len(self.step_summaries) <= 3:
            return False
        total = sum(len(text) for text in self.step_summaries.values())
        if total <= self.budget["step_summaries"]:
            return False

        items = list(self.step_summaries.items())
        keep = OrderedDict(items[-3:])
        old_ids = [step_id for step_id, _ in items[:-3] if step_id != "_history"]
        merged = "已完成: " + ", ".join(old_ids)
        self.step_summaries = OrderedDict([("_history", merged), *keep.items()])
        return True

    def trim_workspace_files(self) -> bool:
        if len(self.workspace_files) <= 5:
            return False
        self.workspace_files = self.workspace_files[-5:]
        return True

    def _extract_summary(self, stdout: str, max_chars: int) -> str:
        stdout = (stdout or "").strip()
        if len(stdout) <= max_chars:
            return stdout
        lines = stdout.splitlines()
        key_lines = []
        current_len = 0
        final_answer = self._extract_final_answer(stdout)
        if final_answer:
            answer_line = f"Final Answer: {final_answer}"
            key_lines.append(answer_line)
            current_len += len(answer_line)
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in key_lines:
                continue
            if any(char.isdigit() for char in stripped) or any(
                token in stripped for token in ("=", ":", "：", "平均", "总计", "异常", "发现")
            ):
                if current_len + len(stripped) > max_chars:
                    break
                key_lines.append(stripped)
                current_len += len(stripped)
        return "\n".join(key_lines) if key_lines else stdout[:max_chars]

    def _extract_findings(self, stdout: str) -> list[str]:
        findings = []
        for line in (stdout or "").splitlines():
            if any(token in line for token in ("发现", "异常", "平均", "最大", "最小", "总计")):
                findings.append(line.strip())
        return [item for item in findings if item][:5]

    def _extract_final_answer(self, stdout: str) -> str:
        text = stdout or ""
        matches = list(re.finditer(
            r"(?:final\s+answer|\u6700\u7ec8\u7b54\u6848|\u7b54\u6848)\s*[:\uff1a]\s*",
            text,
            flags=re.IGNORECASE,
        ))
        if not matches:
            return ""
        answer = text[matches[-1].end():].strip()
        return answer[:2000].rstrip()
