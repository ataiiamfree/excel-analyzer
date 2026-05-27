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
            "代码执行或结果校验失败，请修正。只输出完整 Python 脚本，不要解释。\n"
            "重要：如果报错是 ModuleNotFoundError（模块未安装），你必须改用已安装的库来实现同样的功能，"
            "绝对不要再次导入报错的模块。"
            "可用库：pandas, numpy, matplotlib, openpyxl, seaborn, scipy, pathlib, json, re, collections。"
            "代码中的字符串请使用英文引号，不要使用中文引号。",
            f"## 当前步骤\n{step.description}\n{step.instruction}",
            f"## 数据概况\n{self.format_profile_for_prompt(context.data_profile)}",
            f"## 可用产物\n{self._format_json(context.artifact_manifest)}",
            f"## 失败代码\n```python\n{failed_code}\n```",
            f"## stderr\n{(stderr or '')[-2000:]}",
        ]
        if check_report:
            parts.append(f"## 结果校验失败信息\n{check_report[-2000:]}")
        return "\n\n".join(parts)

    def assemble_adapt(
        self,
        context: TaskContext,
        step: Step,
        step_stdout: str,
    ) -> str:
        """组装 Adapt prompt：轻量 LLM 调用，根据执行结果调整后续计划。"""
        remaining = ""
        if context.plan:
            remaining = context.plan.remaining_steps_overview()

        parts = [
            (
                "你是任务规划助手。刚执行完一个分析步骤，请根据结果判断后续计划是否需要调整。\n\n"
                "## 判断原则\n"
                "- 如果结果揭示了新的信息（如具体阈值、数据分布特征），后续步骤应该利用这些信息\n"
                "- 如果发现了计划中未预料到的情况，可以插入新步骤\n"
                "- 如果发现某些计划步骤已经没有必要，可以跳过\n"
                "- 如果不需要调整，返回空调整\n\n"
                "只输出 JSON，不要解释。"
            ),
            f"## 用户问题\n{context.user_query}",
            f"## 刚完成的步骤\n{step.id}: {step.description}",
            f"## 步骤执行结果摘要\n{(step_stdout or '')[:2000]}",
            f"## 剩余计划\n{remaining or '无剩余步骤'}",
        ]
        if context.key_findings:
            parts.append(f"## 已发现的关键信息\n{self._format_json(context.key_findings)}")

        parts.append(
            '## 输出格式\n```json\n{\n'
            '  "next_step_adjusted": "修改后的下一步指令（null 表示不修改）",\n'
            '  "insert_steps": [{"id": "新步骤ID", "tool": "python", '
            '"description": "描述", "instruction": "指令"}],\n'
            '  "skip_steps": ["要跳过的步骤ID"],\n'
            '  "reasoning": "调整原因"\n'
            "}\n```"
        )
        return "\n\n".join(parts)

    def _build_sections(self, context: TaskContext, current_step: Step) -> list[PromptSection]:
        sections = [
            PromptSection("system", self._load_system_prompt(current_step.tool)),
            PromptSection("user_query", f"## 用户问题\n{context.user_query}"),
            PromptSection(
                "profile",
                f"## 数据概况\n{self.format_profile_for_prompt(context.data_profile)}",
            ),
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
            # 阶段1: 压缩历史摘要
            changed = context.compress_oldest_summaries()
            if changed:
                self._replace_section(
                    sections,
                    "summaries",
                    f"## 前序步骤结果\n{self._format_json(context.step_summaries)}",
                )
                prompt = self._join(sections)
                continue

            # 阶段2: 裁剪文件列表
            changed = context.trim_workspace_files()
            if changed:
                self._replace_or_remove_section(
                    sections,
                    "files",
                    f"## 可用文件\n{self._format_json(context.workspace_files)}",
                )
                prompt = self._join(sections)
                continue

            # 阶段3: 逐个移除 degradable 段（从后往前，保留 system/query/task）
            removed = False
            for i in range(len(sections) - 1, -1, -1):
                if sections[i].degradable:
                    sections.pop(i)
                    prompt = self._join(sections)
                    removed = True
                    break
            if removed:
                continue

            raise PromptBudgetError(
                "Prompt exceeds budget after all degradation attempts. "
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
        # 中文字符约 1-2 token，英文约 1 token / 4 chars
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
        rest = len(text) - cjk
        return max(1, cjk + rest // 4)

    def _format_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)

    def format_profile_for_prompt(self, profile: dict[str, Any]) -> str:
        """Return a compact, path-preserving profile for planner/code prompts."""
        tables = profile.get("tables", []) if isinstance(profile, dict) else []
        if not tables:
            return "无数据表画像。"

        lines = [
            "数据表目录：只能读取每个 table 的 path 指向的正式 normalized 数据文件；"
            "不要用 glob 扫描 normalized 目录，不要读取 *_preview.xlsx。"
        ]
        for index, table in enumerate(tables, start=1):
            table_id = table.get("table_id", f"table_{index}")
            source = table.get("source", "")
            path = table.get("path", "")
            shape = table.get("shape", {})
            rows = shape.get("rows", "?") if isinstance(shape, dict) else "?"
            cols = shape.get("cols", "?") if isinstance(shape, dict) else "?"
            lines.append(
                f"{index}. table_id={table_id}; source={source}; "
                f"path={path}; shape={rows}行x{cols}列"
            )

            columns = self._compact_columns(table)
            if columns:
                lines.append(f"   columns: {', '.join(columns)}")

            enum_columns = table.get("enum_columns") or {}
            enum_text = self._compact_enum_columns(enum_columns)
            if enum_text:
                lines.append(f"   enum_columns: {enum_text}")

            warnings = table.get("warnings") or []
            if warnings:
                lines.append(f"   warnings: {'; '.join(map(str, warnings[:3]))}")
        return "\n".join(lines)

    def _compact_columns(self, table: dict[str, Any]) -> list[str]:
        columns: list[str] = []
        for item in table.get("columns_detail") or []:
            name = item.get("name")
            if not name:
                continue
            dtype = item.get("dtype", "?")
            columns.append(f"{name}({dtype})")

        for group in table.get("columns_grouped") or []:
            pattern = group.get("pattern")
            if not pattern:
                continue
            dtype = group.get("dtype", "?")
            count = group.get("count", "?")
            columns.append(f"{pattern}({dtype}, {count}列)")
        return columns

    def _compact_enum_columns(self, enum_columns: dict[str, Any]) -> str:
        parts = []
        for name, values in list(enum_columns.items())[:8]:
            if not isinstance(values, list):
                continue
            preview = ", ".join(map(str, values[:8]))
            suffix = "..." if len(values) > 8 else ""
            parts.append(f"{name}=[{preview}{suffix}]")
        return "; ".join(parts)

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
                "只输出完整、可直接执行的 Python 脚本，不要输出 JSON 计划、markdown 或解释。\n"
                "可用的 Python 库：pandas, numpy, matplotlib, openpyxl, seaborn, scipy, pathlib, json, re, collections, itertools。"
                "不可用的库：plotly, sklearn, statsmodels, jieba, wordcloud, xlsxwriter。"
                "如果需要这些库的功能，请用可用库替代（如用 numpy 代替 sklearn 做简单统计）。\n"
                "代码中的字符串请使用英文引号，不要使用中文引号（如 \u201c\u201d），否则会导致语法错误。\n"
                "必须优先使用数据概况中 tables[].path 指向的正式数据文件，"
                "不要扫描 normalized 目录，不要读取 *_preview.xlsx。"
                "写代码前必须根据数据概况里的 columns 确认列名；"
                "日期字段可能同时出现 yyyy-mm-dd、yyyy/mm/dd、yyyy.mm.dd、Excel 日期等混合格式，"
                "使用 pandas 转换日期时必须容错处理（如 errors='coerce'，支持时使用 format='mixed'），"
                "不要让单个异常日期格式导致脚本失败。"
                "不同 sheet 的同一业务字段可能列名不同，必须做同义/包含匹配，"
                "例如 送电时间 可匹配 接火送电/送电日期，"
                "报装容量 可匹配 增减容量/新减增容量(kVA)。"
                "把图表和明细写入 output/，用 print 输出摘要和口径。"
            )
        if tool == "knowledge":
            return "你是知识检索助手。只返回与当前步骤相关的来源和摘要。"
        return f"你是 {tool} 执行助手。"
