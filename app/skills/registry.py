"""Skill registry and deterministic intent routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    instructions: str = ""
    path: str | None = None

    def prompt_block(self) -> str:
        parts = [f"## 当前 Skill: {self.name}", self.description]
        if self.allowed_tools:
            parts.append("允许工具: " + ", ".join(self.allowed_tools))
        if self.instructions:
            parts.append(self.instructions.strip())
        return "\n\n".join(parts)


class SkillRegistry:
    def __init__(self, skills: list[SkillSpec] | None = None):
        self._skills: dict[str, SkillSpec] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: SkillSpec) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillSpec:
        return self._skills[name]

    def has(self, name: str) -> bool:
        return name in self._skills

    def names(self) -> list[str]:
        return sorted(self._skills)


class IntentRouter:
    _ARTIFACT_TERMS = (
        "解释", "含义", "怎么看", "是什么", "说明一下", "这个图", "这张图", "这个表",
        "这个文件", "这个产物", "这个附件", "png", "jpg", "jpeg", "csv", "xlsx", "md", "pdf",
    )
    _REPORT_TERMS = ("报告", "汇报", "材料", "撰写", "总结", "word", "不少于")

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def route(
        self,
        query: str,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        has_file: bool = True,
    ) -> SkillSpec:
        artifacts = artifacts or []
        normalized = (query or "").lower()
        visible_artifacts = [
            item for item in artifacts
            if item.get("kind") != "normalized_table"
        ]
        if artifacts and self._mentions_exact_artifact(normalized, artifacts):
            return self.registry.get("artifact_qa")
        if visible_artifacts and self._mentions_artifact_qa_intent(normalized):
            return self.registry.get("artifact_qa")
        if any(term in normalized for term in self._REPORT_TERMS):
            return self.registry.get("report_generation")
        if has_file:
            return self.registry.get("spreadsheet_analysis")
        return self.registry.get("artifact_qa") if artifacts else self.registry.get("spreadsheet_analysis")

    def _mentions_artifact_qa_intent(self, normalized_query: str) -> bool:
        return any(term in normalized_query for term in self._ARTIFACT_TERMS)

    def _mentions_exact_artifact(self, normalized_query: str, artifacts: list[dict[str, Any]]) -> bool:
        for artifact in artifacts:
            name = str(artifact.get("name") or Path(str(artifact.get("path") or "")).name).lower()
            if name and name in normalized_query:
                return True
        return False


def _read_skill(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def build_default_skill_registry(root: str | Path = "skills") -> SkillRegistry:
    base = Path(root)
    skill_defs = [
        SkillSpec(
            name="spreadsheet_analysis",
            description="结构化办公数据分析流程，用于 Excel、CSV 和表格类追问。",
            allowed_tools=["python"],
            instructions=_read_skill(base / "spreadsheet_analysis" / "SKILL.md"),
            path=str(base / "spreadsheet_analysis" / "SKILL.md"),
        ),
        SkillSpec(
            name="artifact_qa",
            description="解释当前会话已生成的图表、导出表、报告和附件。",
            allowed_tools=["artifact_qa"],
            instructions=_read_skill(base / "artifact_qa" / "SKILL.md"),
            path=str(base / "artifact_qa" / "SKILL.md"),
        ),
        SkillSpec(
            name="report_generation",
            description="把已验证的数据分析结果组织成正式报告。",
            allowed_tools=["python"],
            instructions=_read_skill(base / "report_generation" / "SKILL.md"),
            path=str(base / "report_generation" / "SKILL.md"),
        ),
        SkillSpec(
            name="result_validation",
            description="结果校验流程，确保可见结论和产物可追溯。",
            allowed_tools=["result.validate"],
            instructions=_read_skill(base / "result_validation" / "SKILL.md"),
            path=str(base / "result_validation" / "SKILL.md"),
        ),
    ]
    return SkillRegistry(skill_defs)
