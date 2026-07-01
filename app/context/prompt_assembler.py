"""Prompt assembly with explicit budget degradation.

The important rule: never mutate a positional section by index. Optional
sections are named, so budget handling cannot accidentally replace the wrong
part of the prompt.
"""

from __future__ import annotations

import json
import re
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
        stdout: str | None = None,
    ) -> str:
        task_hints = self._format_python_task_hints(context.data_profile)
        parts = [
            "代码执行或结果校验失败，请修正。只输出完整 Python 脚本，不要解释。\n"
            "重要：如果报错是 ModuleNotFoundError（模块未安装），你必须改用已安装的库来实现同样的功能，"
            "绝对不要再次导入报错的模块。"
            "可用库：pandas, numpy, matplotlib, openpyxl, seaborn, scipy, pathlib, json, re, collections。"
            "代码中的字符串请使用英文引号，不要使用中文引号。",
            (
                "如果这是结果校验失败而不是 Python 异常，不要只修格式；必须根据 stdout、数据概况和列名重新检查"
                "筛选条件、列选择、聚合口径和空结果原因。问答类任务最后必须打印一行 `Final Answer: ...`。"
                "如果筛选得到 0 行或答案为 0/空值，先检查条件是否其实出现在列名、重复列族或父级/分组行上下文中，"
                "并在 stdout 中打印候选列、候选行和最终选择依据。"
                "如果校验信息提到重复表头列族，且用户没有明确指定第几列/第几次，禁止用 primary/main/first column "
                "作为选择依据；必须比较同一列族全部有效值并说明选择依据。"
            ),
            f"## 当前步骤\n{step.description}\n{step.instruction}",
            f"## 数据概况\n{self.format_profile_for_prompt(context.data_profile)}",
            f"## 可用产物\n{self._format_json(context.artifact_manifest)}",
            f"## 失败代码\n```python\n{failed_code}\n```",
            f"## stderr\n{(stderr or '')[-2000:]}",
        ]
        if task_hints:
            parts.append(task_hints)
        if stdout:
            parts.append(f"## stdout\n{stdout[-4000:]}")
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
            PromptSection("skill", f"## Skill 约束\n{context.skill_instructions}")
            if context.skill_instructions else PromptSection("skill", ""),
            PromptSection("user_query", f"## 用户问题\n{context.user_query}"),
            PromptSection(
                "profile",
                f"## 数据概况\n{self.format_profile_for_prompt(context.data_profile)}",
            ),
            PromptSection(
                "profile_hints",
                self._format_profile_hints(context.data_profile),
                True,
            ),
            PromptSection(
                "task_hints",
                self._format_python_task_hints(context.data_profile)
                if current_step.tool == "python"
                else "",
                True,
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

            family_text = self._compact_column_families(table.get("column_families") or [])
            if family_text:
                lines.append(f"   column_families: {family_text}")

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

    def _compact_column_families(self, families: list[dict[str, Any]]) -> str:
        parts = []
        for family in families[:8]:
            base = family.get("base")
            columns = family.get("columns") or []
            if not base or not isinstance(columns, list) or len(columns) < 2:
                continue
            preview = ", ".join(map(str, columns[:8]))
            suffix = "..." if len(columns) > 8 else ""
            kind = family.get("kind", "column_family")
            parts.append(f"{base}({kind})=[{preview}{suffix}]")
        return "; ".join(parts)

    def _format_profile_hints(self, profile: dict[str, Any]) -> str:
        tables = profile.get("tables", []) if isinstance(profile, dict) else []
        has_column_families = self._has_column_families(tables)
        has_context_columns = self._has_context_columns(tables)
        if not has_column_families and not has_context_columns:
            return ""
        lines = ["## 表结构提示"]
        if has_context_columns:
            lines.extend(
                [
                    "- `_context_*` 列表示从父级/楼层/分组标题行提取并下传到明细行的上下文。",
                    "- 遇到楼层、区域、部门、类别等条件时，优先用 `_context_*` 过滤明细行；"
                    "不要把 Unit/单位/计量单位列当作楼层或分组列。",
                ]
            )
        if has_column_families:
            lines.extend(
                [
                    "- `column_families` 表示 Excel 重复/多级表头被展开成同一逻辑列族，"
                    "如 `value`, `value_2`, `value_3`；回答前检查全族列，按问题选择成员，不要默认取第一个。",
                    "- 若年份、季度、地区、材料、指标名出现在列名中，优先选列，不要误拿这些条件筛普通行。",
                ]
            )
        return "\n".join(lines)

    def _format_python_task_hints(self, profile: dict[str, Any]) -> str:
        tables = profile.get("tables", []) if isinstance(profile, dict) else []
        if not tables:
            return ""

        lines: list[str] = []
        if self._has_context_columns(tables):
            lines.extend(
                [
                    "`_context_*` 列表示从父级/楼层/分组标题行提取并下传到明细行的上下文。",
                    "遇到楼层、区域、部门、类别等条件时，优先用 `_context_*` 过滤明细行；不要把 Unit/单位/计量单位列当作楼层或分组列。",
                ]
            )
        if self._has_column_families(tables):
            lines.extend(
                [
                    "`column_families` 表示同一逻辑字段的多个表头成员；回答前检查全族列并按用户问题选择成员，不要默认取第一个。",
                    "如果用户没有明确指定第几列/第几次，stdout 中应打印候选列和选择依据。",
                ]
            )
        if self._has_rate_columns(tables):
            lines.append(
                "处理 rate/ratio/percentage/growth 字段时，不要仅因为数值绝对值大于 1 就除以 100；只有列名/单位明确含 % 或样例显示 whole-percent 口径时才转换。"
            )
        if self._has_price_or_cost_pair_columns(tables):
            lines.extend(
                [
                    "当问题引用一个业务指标名但没有完全同名列时，应先列出最接近的列名并选择最接近问题语义的列；不要在工作簿没有定义的情况下自行改造成派生公式。",
                    "如果问题是在比较 A/B 两个实体、材料、地区、年份或版本的某个指标，且表中存在共享同一指标词的 A/B 配对列，应直接使用这些配对列做差或比较。",
                ]
            )
        if not lines:
            return ""
        return "## Python 任务提示\n" + "\n".join(f"- {line}" for line in lines)

    def _has_context_columns(self, tables: list[dict[str, Any]]) -> bool:
        return any(
            str((column.get("name") if isinstance(column, dict) else "") or "").startswith("_context_")
            for table in tables
            for column in table.get("columns_detail") or []
        )

    def _has_column_families(self, tables: list[dict[str, Any]]) -> bool:
        return any(table.get("column_families") for table in tables)

    def _has_rate_columns(self, tables: list[dict[str, Any]]) -> bool:
        names = self._profile_column_names(tables)
        patterns = ("rate", "ratio", "percentage", "growth", "%", "比率", "比例", "增长率", "率")
        return any(any(pattern in name.lower() for pattern in patterns) for name in names)

    def _has_price_or_cost_pair_columns(self, tables: list[dict[str, Any]]) -> bool:
        names = self._profile_column_names(tables)
        for prefix in ("price", "cost"):
            count = sum(
                1
                for name in names
                if self._is_prefix_pair_column(prefix, name)
            )
            if count >= 2:
                return True
        return False

    def _is_prefix_pair_column(self, prefix: str, name: str) -> bool:
        return bool(re.match(rf"^{re.escape(prefix)}(?:[\s_/\-]+|$)", str(name or "").lower()))

    def _profile_column_names(self, tables: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for table in tables:
            for column in table.get("columns_detail") or []:
                name = column.get("name") if isinstance(column, dict) else None
                if name:
                    names.append(str(name))
            for family in table.get("column_families") or []:
                for name in family.get("columns") or []:
                    if name:
                        names.append(str(name))
        return names

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
                "查询/问答类任务必须在 stdout 最后打印一行 `Final Answer: ...`。"
                "筛选文本字段时不要只依赖 == 精确匹配；必须按 exact、strip/casefold normalized exact、contains、"
                "difflib fuzzy candidates 的顺序回退。"
                "如果 exact 匹配为 0 行，不要直接输出 Not Found/N/A；必须打印候选值、尝试包含或模糊匹配后再决定。"
                "当用户询问哪些项目、措施、items、list、all、compare 多个对象时，输出全部匹配项，不要只取第一行。"
                "当用户询问单个命名项目/产品/工程项的数值时，优先定位该项目行；父级/楼层/分组行只作为上下文，"
                "除非问题明确要求 total/sum/aggregate，不要把同一父级下的多行求和。"
                "如果同一 sheet 出现多张同 schema 表，或 warnings 提示续表块，应先 concat 后再筛选/汇总。"
                "层级表或合并单元格展开表中，父级/分组标签可能适用于后续多行；"
                "按子项筛选前应检查是否需要对父级上下文列做 forward-fill 或基于相邻行重建分组范围。"
                "复杂表中可能有重复表头行或合并单元格展开后的标签行，计算前应过滤明显 header-like 行。"
                "如果最终答案仍是空、0、N/A 或 Not Found，stdout 中必须同时打印使用的列名、筛选条件和候选值，便于复核。"
                "把图表和明细写入 output/，用 print 输出摘要和口径。"
            )
        if tool == "artifact_qa":
            return (
                "你是办公数据分析产物解释助手。解释必须基于当前会话 artifact manifest、"
                "生成步骤、脚本、stdout 摘要和图表元数据；不要编造未出现的数据口径。"
            )
        return f"你是 {tool} 执行助手。"
