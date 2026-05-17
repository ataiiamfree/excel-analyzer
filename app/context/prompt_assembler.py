"""Prompt assembly with explicit budget degradation.

The important rule: never mutate a positional section by index. Optional
sections are named, so budget handling cannot accidentally replace the wrong
part of the prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agent.plan import Step
from app.context.task_context import TaskContext


class PromptBudgetError(RuntimeError):
    """Raised when a prompt cannot fit after safe degradation."""


@dataclass
class PromptSection:
    name: str
    content: str
    degradable: bool = False


class PromptAssembler:
    def assemble(self, context: TaskContext, current_step: Step) -> str:
        sections = self._build_sections(context, current_step)
        return self._fit_to_budget(context, sections)

    def assemble_repair(
        self,
        context: TaskContext,
        step: Step,
        failed_code: str,
        stderr: str,
        check_report: str | None = None,
    ) -> str:
        parts = [
            "代码执行或结果校验失败，请修正。只输出完整 Python 脚本，不要解释。",
            f"## 当前步骤\n{step.description}\n{step.instruction}",
            f"## 数据概况\n{self._format_json(context.data_profile)}",
            f"## 可用产物\n{self._format_json(context.artifact_manifest)}",
            f"## 失败代码\n```python\n{failed_code}\n```",
            f"## stderr\n{(stderr or '')[-2000:]}",
        ]
        if check_report:
            parts.append(f"## 结果校验失败信息\n{check_report[-2000:]}")
        return "\n\n".join(parts)

    def _build_sections(self, context: TaskContext, current_step: Step) -> list[PromptSection]:
        sections = [
            PromptSection("system", self._load_system_prompt(current_step.tool)),
            PromptSection("user_query", f"## 用户问题\n{context.user_query}"),
            PromptSection("profile", f"## 数据概况\n{self._format_json(context.data_profile)}", True),
            PromptSection(
                "plan",
                f"## 执行计划\n{self._format_plan_overview(context.plan, current_step.id)}",
            ),
        ]
        if context.step_summaries:
            sections.append(
                PromptSection(
                    "summaries",
                    f"## 前序步骤结果\n{self._format_json(context.step_summaries)}",
                    True,
                )
            )
        if context.key_findings:
            sections.append(
                PromptSection(
                    "findings",
                    f"## 已发现的关键信息\n{self._format_json(context.key_findings)}",
                    True,
                )
            )
        if context.artifact_manifest:
            sections.append(
                PromptSection(
                    "artifacts",
                    f"## 可用产物\n{self._format_json(context.artifact_manifest)}",
                    True,
                )
            )
        if context.workspace_files:
            sections.append(
                PromptSection(
                    "files",
                    f"## 可用文件\n{self._format_json(context.workspace_files)}",
                    True,
                )
            )
        sections.append(PromptSection("task", f"## 当前任务\n{current_step.instruction}"))
        return sections

    def _fit_to_budget(self, context: TaskContext, sections: list[PromptSection]) -> str:
        max_tokens = context.budget["max_prompt_tokens"]
        prompt = self._join(sections)
        while self._count_tokens(prompt) > max_tokens:
            changed = context.compress_oldest_summaries()
            if changed:
                self._replace_section(
                    sections,
                    "summaries",
                    f"## 前序步骤结果\n{self._format_json(context.step_summaries)}",
                )
                prompt = self._join(sections)
                continue

            changed = context.trim_workspace_files()
            if changed:
                self._replace_or_remove_section(
                    sections,
                    "files",
                    f"## 可用文件\n{self._format_json(context.workspace_files)}",
                )
                prompt = self._join(sections)
                continue

            raise PromptBudgetError(
                "Prompt exceeds budget after compressing summaries and file lists. "
                "Reduce profile/detail size before calling the LLM."
            )
        return prompt

    def _replace_section(self, sections: list[PromptSection], name: str, content: str) -> None:
        for section in sections:
            if section.name == name:
                section.content = content
                return

    def _replace_or_remove_section(
        self, sections: list[PromptSection], name: str, content: str
    ) -> None:
        for index, section in enumerate(sections):
            if section.name == name:
                if content.strip():
                    section.content = content
                else:
                    sections.pop(index)
                return

    def _join(self, sections: list[PromptSection]) -> str:
        return "\n\n".join(section.content for section in sections if section.content.strip())

    def _count_tokens(self, text: str) -> int:
        # Conservative enough for budget tests without requiring tiktoken at import time.
        return max(1, len(text) // 3)

    def _format_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)

    def _format_plan_overview(self, plan: Any, current_step_id: str) -> str:
        if plan is None:
            return "尚未生成计划"
        lines = []
        for step in plan.steps:
            marker = "current" if step.id == current_step_id else step.status
            lines.append(f"- [{marker}] {step.id}: {step.description}")
        return "\n".join(lines)

    def _load_system_prompt(self, tool: str) -> str:
        if tool == "python":
            return (
                "你是 Python 数据分析专家。读取 normalized parquet/xlsx，"
                "把图表和明细写入 output/，用 print 输出摘要和口径。"
            )
        if tool == "knowledge":
            return "你是知识检索助手。只返回与当前步骤相关的来源和摘要。"
        return f"你是 {tool} 执行助手。"
