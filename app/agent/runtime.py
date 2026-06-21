"""Python-side agent runtime for the Pi sidecar.

The API layer talks to this module instead of depending on the legacy
plan-execute orchestrator. Pi owns the agent loop; Python keeps the trusted
runtime boundary for typed tool execution, artifact manifests, and event
mapping.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import asyncio
import json
import os
import shlex
from typing import Any

from app.agent.plan import ExecutionPlan, Step
from app.agent.types import StepResult, TaskResult
from app.skills.registry import IntentRouter, SkillRegistry, build_default_skill_registry
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.workspace import Workspace

PiEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RuntimeRequest:
    query: str
    session: Any
    callbacks: dict[str, Any] = field(default_factory=dict)


class RuntimeUnavailableError(RuntimeError):
    """Raised when a configured runtime cannot be started."""


class PiRuntimeError(RuntimeError):
    """Raised when the Pi sidecar reports a runtime failure."""


class AgentRuntimeAdapter:
    name = "base"

    async def run(self, request: RuntimeRequest) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


class PiRpcTransport:
    """JSONL client for `pi --mode rpc --no-session`.

    The official Pi RPC protocol sends one JSON command per stdin line and
    streams responses/events as JSON lines on stdout.
    """

    def __init__(
        self,
        *,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stream_limit_bytes: int = 16 * 1024 * 1024,
        process_factory: Callable[..., Awaitable[Any]] | None = None,
    ):
        if not command:
            raise ValueError("Pi command cannot be empty")
        self.command = command
        self.cwd = cwd
        self.env = env
        self.stream_limit_bytes = stream_limit_bytes
        self.process_factory = process_factory

    async def run(self, payload: dict[str, Any], event_handler: PiEventHandler) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or payload.get("query") or "")
        proc = await self._start()
        command_id = f"prompt-{payload.get('session_id') or 'run'}"
        await self._send(proc, {"id": command_id, "type": "prompt", "message": prompt})

        event_count = 0
        saw_agent_end = False
        try:
            while True:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8").rstrip("\r\n") if isinstance(raw_line, bytes) else str(raw_line).rstrip("\r\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError as exc:
                    raise PiRuntimeError(f"Pi emitted invalid JSONL: {line[:200]}") from exc
                if event.get("type") == "response" and event.get("id") == command_id:
                    if not event.get("success", False):
                        raise PiRuntimeError(str(event.get("error") or "Pi prompt command failed"))
                    continue
                event_count += 1
                await event_handler(event)
                if event.get("type") == "agent_end":
                    saw_agent_end = True
                    break
        finally:
            await self._stop(proc)

        if not saw_agent_end:
            raise PiRuntimeError("Pi RPC stream ended before agent_end")
        return {"event_count": event_count}

    async def _start(self) -> Any:
        try:
            if self.process_factory is not None:
                return await self.process_factory(
                    self.command,
                    cwd=self.cwd,
                    env=self.env,
                )
            return await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=self.env,
                limit=self.stream_limit_bytes,
            )
        except FileNotFoundError as exc:
            raise RuntimeUnavailableError(f"Pi command not found: {self.command[0]}") from exc

    async def _send(self, proc: Any, command: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeUnavailableError("Pi stdin is not available")
        line = json.dumps(command, ensure_ascii=False) + "\n"
        data = line.encode("utf-8")
        proc.stdin.write(data)
        drain = getattr(proc.stdin, "drain", None)
        if drain is not None:
            await drain()

    async def _stop(self, proc: Any) -> None:
        stdin = getattr(proc, "stdin", None)
        if stdin is not None:
            close = getattr(stdin, "close", None)
            if close is not None:
                close()
        returncode = getattr(proc, "returncode", None)
        if returncode is None:
            terminate = getattr(proc, "terminate", None)
            if terminate is not None:
                terminate()
        wait = getattr(proc, "wait", None)
        if wait is not None:
            try:
                await asyncio.wait_for(wait(), timeout=2)
            except asyncio.TimeoutError:
                kill = getattr(proc, "kill", None)
                if kill is not None:
                    kill()


class PiEventMapper:
    """Map Pi SDK/RPC events into the API runner callback shape."""

    final_marker = "<<FINAL_REPORT>>"

    def __init__(self, callbacks: dict[str, Any], step: Step):
        self.callbacks = callbacks
        self.step = step
        self.started = False
        self.report_parts: list[str] = []
        self.raw_text_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.tool_events: list[str] = []
        self.report_started = False

    @property
    def report(self) -> str:
        return "".join(self.report_parts).strip()

    @property
    def stdout(self) -> str:
        parts = []
        if self.reasoning_parts:
            parts.append("".join(self.reasoning_parts).strip())
        if self.tool_events:
            parts.append("\n".join(self.tool_events).strip())
        return "\n\n".join(part for part in parts if part).strip()

    async def handle(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "agent_start":
            await self.ensure_started()
            return
        if event_type == "message_update":
            await self.ensure_started()
            await self._handle_message_update(event)
            return
        if event_type == "tool_execution_start":
            await self.ensure_started()
            await self._tool_line(f"工具开始: {event.get('toolName')}", event.get("args"))
            return
        if event_type == "tool_execution_update":
            await self.ensure_started()
            await self._tool_line(f"工具输出: {event.get('toolName')}", event.get("partialResult"))
            return
        if event_type == "tool_execution_end":
            await self.ensure_started()
            label = "失败" if event.get("isError") else "完成"
            await self._tool_line(f"工具{label}: {event.get('toolName')}", event.get("result"))
            return
        if event_type == "agent_end":
            await self.ensure_started()
            if not self.report_parts:
                text = _last_assistant_text(event.get("messages") or []) or "".join(self.raw_text_parts)
                if text:
                    await self._emit_report(_extract_final_report(text, self.final_marker))

    async def ensure_started(self) -> None:
        if self.started:
            return
        self.started = True
        on_plan_ready = self.callbacks.get("on_plan_ready")
        if on_plan_ready is not None:
            await on_plan_ready(ExecutionPlan(steps=[self.step]))
        on_step_start = self.callbacks.get("on_step_start")
        if on_step_start is not None:
            await on_step_start(self.step, 1, 1)

    async def finish(self, *, failed: bool, error: str = "", files: list[str] | None = None) -> None:
        if not self.started:
            return
        on_step_end = self.callbacks.get("on_step_end")
        if on_step_end is not None:
            await on_step_end(
                self.step,
                StepResult(
                    stdout=self.stdout,
                    files=files or [],
                    failed=failed,
                    error=error,
                ),
            )

    async def _handle_message_update(self, event: dict[str, Any]) -> None:
        update = event.get("assistantMessageEvent") or {}
        update_type = update.get("type")
        if update_type == "text_delta":
            delta = str(update.get("delta") or "")
            if delta:
                self.raw_text_parts.append(delta)
                raw_text = "".join(self.raw_text_parts)
                if self.report_started:
                    await self._emit_report(delta)
                    return
                marker_index = raw_text.find(self.final_marker)
                if marker_index >= 0:
                    self.report_started = True
                    final_text = raw_text[marker_index + len(self.final_marker):]
                    if final_text:
                        await self._emit_report(final_text)
                    return
                self.reasoning_parts.append(delta)
                callback = self.callbacks.get("on_reasoning_token")
                if callback is not None:
                    await callback(delta)
        elif update_type == "thinking_delta":
            delta = str(update.get("delta") or update.get("thinking") or "")
            if delta:
                self.reasoning_parts.append(delta)
                callback = self.callbacks.get("on_reasoning_token")
                if callback is not None:
                    await callback(delta)

    async def _emit_report(self, text: str) -> None:
        if not text:
            return
        self.report_parts.append(text)
        callback = self.callbacks.get("on_report_token")
        if callback is not None:
            await callback(text)

    async def _tool_line(self, prefix: str, data: Any) -> None:
        text = prefix
        if data not in (None, ""):
            text += "\n" + _compact_json(data)
        self.tool_events.append(text)
        callback = self.callbacks.get("on_reasoning_token")
        if callback is not None:
            await callback("\n" + text + "\n")


class PiSidecarRuntimeAdapter(AgentRuntimeAdapter):
    """Primary runtime backed by Pi RPC."""

    name = "pi-sidecar"

    def __init__(
        self,
        *,
        config: Any,
        transport: Any,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
    ):
        self.config = config
        self.transport = transport
        self.tool_registry = tool_registry or build_default_tool_registry()
        self.skill_registry = skill_registry or build_default_skill_registry()
        self.intent_router = IntentRouter(self.skill_registry)

    async def run(self, request: RuntimeRequest) -> TaskResult:
        workspace = Workspace(root=self.config.workspace_dir, task_id=request.session.session_id)
        artifacts = workspace.read_artifact_manifest()
        skill = self.intent_router.route(
            request.query,
            artifacts=artifacts,
            has_file=bool(getattr(request.session, "file_path", None)),
        )
        payload = {
            "query": request.query,
            "session_id": getattr(request.session, "session_id", None),
            "file_path": getattr(request.session, "file_path", None),
            "workspace_path": str(workspace.path),
            "workspace_root": self.config.workspace_dir,
            "prior_tasks": list(getattr(request.session, "tasks", [])),
            "skill": skill.name,
            "skill_instructions": skill.prompt_block(),
            "tools": [
                _tool_payload(self.tool_registry.get(tool_name))
                for tool_name in self.tool_registry.names()
            ],
            "artifact_manifest": artifacts,
        }
        payload["prompt"] = self._build_prompt(payload)
        step = Step(
            id="pi-runtime",
            tool="pi",
            description=f"Pi Agent Runtime · {skill.name}",
            instruction=request.query,
            is_exploratory=False,
        )
        mapper = PiEventMapper(request.callbacks, step)
        try:
            result = await self.transport.run(payload, mapper.handle)
        except Exception as exc:
            await mapper.finish(failed=True, error=str(exc), files=[])
            raise
        files = list(result.get("files") or workspace.list_output_files())
        await mapper.finish(failed=False, files=files)
        report = str(result.get("report") or mapper.report or "")
        if not report:
            report = "Pi runtime 已完成，但没有返回可展示文本。"
        return TaskResult(report=report, files=files, failed=False)

    def _build_prompt(self, payload: dict[str, Any]) -> str:
        tool_lines = "\n".join(
            f"- {tool['name']}: {tool['description']}" for tool in payload.get("tools", [])
        ) or "- 当前 skill 无 planner-visible 工具"
        service_command = (
            "python -m app.agent.pi_tool_service "
            f"--workspace-root {shlex.quote(str(payload['workspace_root']))} "
            f"--session-id {shlex.quote(str(payload['session_id']))} "
            f"--file-path {shlex.quote(str(payload.get('file_path') or ''))} "
            "--tool <tool-name> --arguments-json '<json-arguments>'"
        )
        artifacts = _compact_json(payload.get("artifact_manifest") or [])
        return (
            "你是办公数据分析平台的主 Agent Runtime，运行在 Pi sidecar 中。\n"
            "你负责规划、选择工具、解释工具结果并输出最终中文回答。\n\n"
            "硬约束：\n"
            "1. 不直接读取或改写原始办公文件；必须通过下面的 Python typed tool service 调用后端工具。\n"
            "2. 用户可见产物必须写入当前 workspace 的 output/，并由工具服务登记 Artifact Graph。\n"
            "3. 不要泄露 API key、环境变量或 workspace 外路径。\n"
            "4. 如果用户询问已生成产物，优先调用 artifact.explain 或 artifact.inspect，不重新分析原始文件。\n\n"
            "输出约束：\n"
            f"- 只有准备给用户最终报告时，才输出 `{PiEventMapper.final_marker}`，后面紧跟最终报告正文。\n"
            "- marker 之前不要输出任何给用户看的执行过程。\n"
            "- 最终报告中禁止描述工具调用、参数调整、路径排查、沙箱重试等过程性文字。\n\n"
            f"当前 session: {payload.get('session_id')}\n"
            f"当前 workspace: {payload.get('workspace_path')}\n"
            f"当前文件: {payload.get('file_path') or '无'}\n"
            f"当前 skill: {payload.get('skill')}\n\n"
            f"Skill 约束：\n{payload.get('skill_instructions')}\n\n"
            f"可用工具：\n{tool_lines}\n\n"
            "工具调用方式：\n"
            f"{service_command}\n\n"
            "其中 <tool-name> 可以使用 canonical tool name，也可以使用 registry alias。\n\n"
            "当前 Artifact Manifest 摘要：\n"
            f"{artifacts[:4000]}\n\n"
            f"用户需求：\n{payload.get('query')}\n"
        )


def build_agent_runtime(
    config: Any,
    *,
    pi_transport: Any | None = None,
) -> AgentRuntimeAdapter:
    """Build the single supported Python-side runtime."""

    return PiSidecarRuntimeAdapter(
        config=config,
        transport=pi_transport or build_pi_rpc_transport(config),
    )


def build_pi_rpc_transport(config: Any) -> PiRpcTransport:
    command = [str(getattr(config, "pi_command", "pi"))]
    extra_args = shlex.split(str(getattr(config, "pi_args", "--mode rpc --no-session")))
    command.extend(extra_args)
    provider = str(getattr(config, "pi_provider", "") or "")
    model = str(getattr(config, "pi_model", "") or "")
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    env = os.environ.copy()
    return PiRpcTransport(
        command=command,
        cwd=str(getattr(config, "pi_cwd", "") or os.getcwd()),
        env=env,
        stream_limit_bytes=int(getattr(config, "pi_stream_limit_bytes", 16 * 1024 * 1024)),
    )


def _tool_payload(tool: Any) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "permissions": tool.permissions,
        "aliases": tool.aliases,
    }


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "".join(parts).strip()
    return ""


def _extract_final_report(text: str, marker: str) -> str:
    if not text:
        return ""
    marker_index = text.find(marker)
    if marker_index >= 0:
        return text[marker_index + len(marker):].strip()

    candidates = (
        "## 📊 分析结果",
        "## 分析结果",
        "# 分析结果",
        "分析结果：",
        "分析结果:",
        "最终答案：",
        "最终答案:",
        "结论如下：",
        "结论如下:",
    )
    indexes = [text.find(candidate) for candidate in candidates if text.find(candidate) >= 0]
    if indexes:
        return text[min(indexes):].strip()
    return text.strip()
