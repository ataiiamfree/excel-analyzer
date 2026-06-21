"""Typed tool registry for agent-visible and internal platform tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ToolRegistryError(RuntimeError):
    """Base error for tool registry problems."""


class UnknownToolError(ToolRegistryError):
    """Raised when an agent plan references an unregistered tool."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    handler: Callable[..., Any] | None = None
    produces_artifacts: bool = False
    deterministic: bool = True
    planner_visible: bool = False
    skill_names: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def prompt_line(self) -> str:
        return f"- {self.name}: {self.description}"


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass
class ToolResult:
    tool_name: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec] | None = None):
        self._tools: dict[str, ToolSpec] = {}
        self._aliases: dict[str, str] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ToolRegistryError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            if alias in self._aliases and self._aliases[alias] != tool.name:
                raise ToolRegistryError(f"Tool alias already registered: {alias}")
            self._aliases[alias] = tool.name

    def get(self, name: str) -> ToolSpec:
        canonical = self.normalize_name(name)
        try:
            return self._tools[canonical]
        except KeyError as exc:
            raise UnknownToolError(f"未注册的工具: {name}") from exc

    def has(self, name: str) -> bool:
        try:
            self.get(name)
        except UnknownToolError:
            return False
        return True

    def normalize_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def ensure_registered(self, name: str) -> None:
        self.get(name)

    def planner_tools(self, skill_name: str | None = None) -> list[ToolSpec]:
        tools = [tool for tool in self._tools.values() if tool.planner_visible]
        if skill_name:
            tools = [
                tool for tool in tools
                if not tool.skill_names or skill_name in tool.skill_names
            ]
        return sorted(tools, key=lambda tool: tool.name)

    def planner_prompt(self, skill_name: str | None = None) -> str:
        tools = self.planner_tools(skill_name)
        if not tools:
            return "无可用工具。"
        return "\n".join(tool.prompt_line() for tool in tools)

    def names(self) -> list[str]:
        return sorted(self._tools)


def build_default_tool_registry() -> ToolRegistry:
    """Return the platform tool catalog.

    Planner-visible names stay concise for compatibility with existing plans.
    Canonical long names are still registered so future harness integrations can
    call typed tools directly.
    """

    return ToolRegistry([
        ToolSpec(
            name="python",
            description="生成并在受控沙箱中执行 Python 数据分析脚本，用户可见产物必须写入 output/。",
            permissions=["workspace:read", "workspace:write_output", "sandbox:execute"],
            produces_artifacts=True,
            deterministic=False,
            planner_visible=True,
            skill_names=["spreadsheet_analysis", "report_generation"],
            aliases=["code.run_python_sandboxed"],
        ),
        ToolSpec(
            name="artifact_qa",
            description="解释当前会话中已生成的图表、导出表、报告或其他产物，不重新分析原始文件。",
            permissions=["workspace:read", "artifact:read"],
            deterministic=True,
            planner_visible=True,
            skill_names=["artifact_qa"],
            aliases=["artifact.explain"],
        ),
        ToolSpec(
            name="spreadsheet.ingest_workbook",
            description="扫描 workbook/sheet/table 结构并生成 manifest。",
            permissions=["workspace:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="spreadsheet.normalize_tables",
            description="把原始 spreadsheet 标准化为 normalized tables。",
            permissions=["workspace:read", "workspace:write_normalized"],
            produces_artifacts=True,
            deterministic=True,
        ),
        ToolSpec(
            name="spreadsheet.profile_tables",
            description="生成 normalized tables 的列类型、枚举值、样例和统计画像。",
            permissions=["workspace:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="result.validate",
            description="校验步骤执行结果、预期产物和基础不变量。",
            permissions=["workspace:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="artifact.list",
            description="列出当前会话可用产物。",
            permissions=["artifact:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="artifact.inspect",
            description="读取产物元数据、血缘、脚本路径和预览信息。",
            permissions=["artifact:read", "workspace:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="artifact.resolve_by_name",
            description="根据用户问题中的文件名或关键词匹配产物。",
            permissions=["artifact:read"],
            deterministic=True,
        ),
        ToolSpec(
            name="report.generate",
            description="基于已验证步骤摘要和产物生成 Markdown 报告。",
            permissions=["artifact:read"],
            produces_artifacts=True,
            deterministic=False,
        ),
    ])
