"""Adaptive Plan-Execute orchestrator skeleton.

This file focuses on the state transitions that are easy to get wrong:
failed steps are not marked done, check-repair has an explicit path, and step
dispatch goes through a registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import json
import logging
from pathlib import Path

from app.agent.plan import ExecutionPlan, PlanAdjustment, Step
from app.agent.reporter import Reporter
from app.context.prompt_assembler import PromptAssembler
from app.context.task_context import TaskContext
from app.session import Session
from app.tools.result_checker import CheckResult
from app.workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    output_files: list[str] = field(default_factory=list)
    script_path: str | None = None


@dataclass
class StepResult:
    stdout: str
    files: list[str]
    failed: bool = False
    error: str = ""
    retries_exhausted: bool = False
    script_path: str | None = None

    @property
    def success(self) -> bool:
        return not self.failed

    @property
    def stderr(self) -> str:
        return self.error

    @property
    def output_files(self) -> list[str]:
        return self.files


@dataclass
class TaskResult:
    report: str
    files: list[str]


Executor = Callable[[Step, TaskContext, Any], Awaitable[StepResult]]


class Orchestrator:
    def __init__(self, llm_client: Any, tools: Any, config: Any):
        self.llm = llm_client
        self.tools = tools
        self.config = config
        self.assembler = PromptAssembler()
        self.reporter = Reporter(llm_client=llm_client)
        self.executors: dict[str, Executor] = {
            "python": self._execute_python,
            "knowledge": self._execute_knowledge,
        }

    # ------------------------------------------------------------------
    # Top-level entry: full pipeline
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        session: Session,
        *,
        on_step_start: Callable[[Step], Awaitable[None]] | None = None,
        on_step_end: Callable[[Step, StepResult], Awaitable[None]] | None = None,
    ) -> TaskResult:
        """Full pipeline: Ingest → Preprocess → Profile → Plan → Execute → Report.

        On follow-ups (session.is_follow_up), skips Ingest/Preprocess/Profile
        and reuses cached session data.
        """
        workspace = Workspace(root=self.config.workspace_dir)

        if session.is_follow_up and session.profile is not None:
            # 追问：复用已有预处理结果
            manifest = session.workbook_manifest or {}
            profile = session.profile
        else:
            # 首次分析：全流程
            raw_file_path = Path(workspace.save_upload(session.file_path)).resolve()
            normalized_dir = (Path(workspace.path) / "normalized").resolve()
            manifest = self.tools.ingestor.scan(raw_file_path)
            preprocess_result = self.tools.preprocessor.process(
                file_path=raw_file_path,
                manifest=manifest,
                output_dir=normalized_dir,
            )
            tables = preprocess_result.tables
            workspace.save_artifacts(tables)
            profile = self.tools.profiler.profile(tables)
            session.cache_preprocessing(
                workbook_manifest=manifest,
                profile=profile,
                normalized_dir=str(normalized_dir),
            )

        # 构建 TaskContext
        context = TaskContext(
            task_id=workspace.task_id,
            user_query=query,
            workbook_manifest=manifest,
            data_profile=profile,
            budget_preset=self.config.budget_preset,
        )

        # 追问时注入前序上下文
        if session.is_follow_up:
            follow_up = session.build_follow_up_context()
            context.key_findings = follow_up.get("prior_findings", [])

        # LLM 规划
        plan = await self._plan(context, session)
        workspace.save_json("plan.json", plan.to_dict())

        # 执行
        self._on_step_start = on_step_start
        self._on_step_end = on_step_end
        result = await self.run_plan(plan, context, workspace)

        # 更新 session
        session.update_after_task(
            task_id=workspace.task_id,
            findings=context.key_findings,
            summary_text=query,
        )

        return result

    async def _plan(self, context: TaskContext, session: Session) -> ExecutionPlan:
        """Call LLM to generate an execution plan."""
        profile_text = self.assembler.format_profile_for_prompt(context.data_profile)

        follow_up_section = ""
        if session.is_follow_up:
            follow_up = session.build_follow_up_context()
            follow_up_section = (
                f"\n## 前序分析上下文\n"
                f"已完成任务: {follow_up['prior_tasks']}\n"
                f"已有发现: {follow_up['prior_findings'][:10]}\n"
                f"对话摘要: {follow_up['conversation_summary'][:500]}\n"
            )

        prompt = (
            "你是数据分析规划器。根据用户需求和数据概况，输出 JSON 格式的执行计划。\n\n"
            f"## 用户需求\n{context.user_query}\n\n"
            f"## 数据概况\n{profile_text}\n"
            f"{follow_up_section}\n"
            "## 输出格式\n"
            "返回 JSON：\n"
            "```json\n"
            '{\n  "steps": [\n'
            '    {"id": "s1", "tool": "python", "description": "...", "instruction": "...", '
            '"is_exploratory": false, "depends_on": []}\n'
            "  ],\n"
            '  "report_outline": [\n'
            '    {"title": "...", "related_steps": ["s1"], "word_count": 800}\n'
            "  ]\n"
            "}\n```\n"
            "tool 只能是 python 或 knowledge。\n"
            "确保 steps 按执行顺序排列，depends_on 引用已有 step id。\n"
        )

        response = await self.llm.call(prompt, max_tokens=2000)
        return self._parse_plan(response)

    def _parse_plan(self, response: str) -> ExecutionPlan:
        """Parse LLM response into an ExecutionPlan with fallback."""
        text = response.strip()

        # Try extracting from code block
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict) and "steps" in data:
                        return self._dict_to_plan(data)
                except (json.JSONDecodeError, ValueError):
                    continue

        # Try parsing whole response as JSON
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "steps" in data:
                return self._dict_to_plan(data)
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: single generic step
        logger.warning("无法解析 Plan 响应，使用默认单步计划")
        return ExecutionPlan(steps=[
            Step(
                id="s1",
                tool="python",
                description="分析数据",
                instruction=f"根据用户需求分析数据: {text[:200]}",
                is_exploratory=True,
            ),
        ])

    def _dict_to_plan(self, data: dict) -> ExecutionPlan:
        steps = []
        for item in data.get("steps", []):
            if isinstance(item, dict) and item.get("id"):
                steps.append(Step(
                    id=item["id"],
                    tool=item.get("tool", "python"),
                    description=item.get("description", ""),
                    instruction=item.get("instruction", ""),
                    depends_on=item.get("depends_on", []),
                    is_exploratory=item.get("is_exploratory", False),
                ))
        outline = data.get("report_outline", [])
        return ExecutionPlan(steps=steps, report_outline=outline)

    async def run_plan(
        self,
        plan: ExecutionPlan,
        context: TaskContext,
        workspace: Any,
    ) -> TaskResult:
        context.plan = plan
        while True:
            if workspace.is_cancel_requested():
                workspace.write_state(status="cancelled", current_step=None)
                return TaskResult(report="任务已取消", files=[])

            step = plan.next_runnable_step()
            if step is None:
                break

            plan.mark_running(step.id)
            workspace.write_state(status="executing", current_step=step.id)

            on_start = getattr(self, "_on_step_start", None)
            if on_start:
                await on_start(step)

            result = await self._execute_step(step, context, workspace)
            check = self.tools.checker.validate(step, result, context, workspace)

            if check.status == "failed" and not result.retries_exhausted:
                result = await self._repair_from_check(step, result, check, context, workspace)
                check = self.tools.checker.validate(step, result, context, workspace)

            if result.failed or check.status == "failed":
                plan.mark_failed(step.id, result.error or check.to_prompt_text(), check.status)
                if result.retries_exhausted and hasattr(self.tools, "planner"):
                    plan = await self._replan(context, step, result.error or check.to_prompt_text())
                    context.plan = plan
                    workspace.save_json("plan.json", plan.to_dict())
                    continue
                workspace.write_state(
                    status="failed",
                    current_step=step.id,
                    error=result.error or check.to_prompt_text(),
                )
                return TaskResult(report="任务失败，已停止在当前步骤", files=[])

            context.quality_checks.append(check)
            context.add_step_summary(step.id, result.stdout, step.description)

            # 自动注册步骤产出的文件（图表/Excel/CSV 等）
            for fpath in result.output_files:
                workspace.register_artifact(
                    path=fpath,
                    kind=self._infer_artifact_kind(fpath),
                    producer_step=step.id,
                    description=step.description,
                )

            context.update_workspace_files(workspace.list_files())
            context.update_artifacts(workspace.read_artifact_manifest())
            plan.mark_done(step.id, check=check.status)
            workspace.save_json("plan.json", plan.to_dict())

            on_end = getattr(self, "_on_step_end", None)
            if on_end:
                await on_end(step, result)

            # Adaptive: 根据结果动态调整后续计划
            if self._should_adapt(step, result, plan.remaining_steps()):
                adjustment = await self._adapt(context, step, result)
                plan.apply_adjustment(adjustment, current_step_id=step.id)
                workspace.save_json("plan.json", plan.to_dict())

        # 生成报告（有 outline 时分章节 LLM 调用，无 outline 时简单汇总）
        try:
            report = await self.reporter.generate(context, workspace)
        except Exception:
            logger.exception("Reporter 生成报告失败，降级为简单汇总")
            report = self.reporter._assemble_simple_response(context, workspace)

        # 保存报告到 output/report.md 并注册产物
        report_path = Path(workspace.path) / "output" / "report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        workspace.register_artifact(
            path="output/report.md",
            kind="report",
            producer_step="reporter",
            description="分析报告",
        )

        workspace.write_state(status="completed", current_step=None)
        return TaskResult(report=report, files=self._absolute_output_files(workspace))

    async def _execute_step(self, step: Step, context: TaskContext, workspace: Any) -> StepResult:
        executor = self.executors.get(step.tool)
        if executor is None:
            return StepResult(
                stdout="",
                files=[],
                failed=True,
                error=f"未注册的 skill 类型: {step.tool}",
                retries_exhausted=True,
            )
        return await executor(step, context, workspace)

    async def _execute_knowledge(
        self, step: Step, context: TaskContext, workspace: Any
    ) -> StepResult:
        chunks = self.tools.knowledge.search(step.instruction, top_k=3)
        return StepResult(stdout=str(chunks), files=[])

    async def _execute_python(
        self, step: Step, context: TaskContext, workspace: Any
    ) -> StepResult:
        prompt = self.assembler.assemble(context, step)
        code_response = await self.llm.call(prompt)
        code = self._extract_code_block(code_response)
        exec_result = self.tools.sandbox.execute(
            code=code,
            workdir=workspace.path,
            step_id=step.id,
            attempt=0,
            timeout=self.config.sandbox_timeout,
        )
        workspace.record_code(step.id, exec_result.script_path, attempt=0)

        for attempt in range(self.config.max_repair_attempts):
            if exec_result.success:
                break
            repair_prompt = self.assembler.assemble_repair(
                context, step, code, exec_result.stderr
            )
            code = self._extract_code_block(await self.llm.call(repair_prompt))
            exec_result = self.tools.sandbox.execute(
                code=code,
                workdir=workspace.path,
                step_id=step.id,
                attempt=attempt + 1,
                timeout=self.config.sandbox_timeout,
            )
            workspace.record_code(step.id, exec_result.script_path, attempt=attempt + 1)

        return StepResult(
            stdout=exec_result.stdout,
            files=exec_result.output_files,
            failed=not exec_result.success,
            error=exec_result.stderr,
            retries_exhausted=not exec_result.success,
            script_path=exec_result.script_path,
        )

    async def _repair_from_check(
        self,
        step: Step,
        result: StepResult,
        check: CheckResult,
        context: TaskContext,
        workspace: Any,
    ) -> StepResult:
        script_text = workspace.read_text(result.script_path) if result.script_path else ""
        repair_prompt = self.assembler.assemble_repair(
            context,
            step,
            failed_code=script_text,
            stderr=result.error,
            check_report=check.to_prompt_text(),
        )
        code = self._extract_code_block(await self.llm.call(repair_prompt))
        exec_result = self.tools.sandbox.execute(
            code=code,
            workdir=workspace.path,
            step_id=step.id,
            attempt=self.config.max_repair_attempts + 1,
            timeout=self.config.sandbox_timeout,
        )
        workspace.record_code(
            step.id, exec_result.script_path, attempt=self.config.max_repair_attempts + 1
        )
        return StepResult(
            stdout=exec_result.stdout,
            files=exec_result.output_files,
            failed=not exec_result.success,
            error=exec_result.stderr,
            retries_exhausted=not exec_result.success,
            script_path=exec_result.script_path,
        )

    async def _replan(
        self, context: TaskContext, failed_step: Step, error: str
    ) -> ExecutionPlan:
        if not hasattr(self.tools, "planner"):
            context.plan.mark_failed(failed_step.id, error)  # type: ignore[union-attr]
            return context.plan  # type: ignore[return-value]
        return await self.tools.planner.replan(context, failed_step, error)

    def _should_adapt(self, step: Step, result: StepResult, remaining_steps: list[Step]) -> bool:
        """判断是否需要 Adapt 调整后续计划。"""
        if not remaining_steps:
            return False
        if result.failed:
            return True
        if step.is_exploratory:
            return True
        if self._has_unexpected_findings(result.stdout):
            return True
        return False

    def _has_unexpected_findings(self, stdout: str) -> bool:
        """检测 stdout 中是否包含需要调整计划的信号。"""
        keywords = ("异常", "意外", "发现", "warning", "注意", "错误率", "缺失率超过")
        return any(kw in (stdout or "") for kw in keywords)

    async def _adapt(self, context: TaskContext, step: Step, result: StepResult) -> PlanAdjustment:
        """轻量 LLM 调用，根据执行结果调整后续计划。"""
        prompt = self.assembler.assemble_adapt(context, step, result.stdout)
        response = await self.llm.call(prompt, max_tokens=500)
        return self._parse_adjustment(response)

    def _parse_adjustment(self, response: str) -> PlanAdjustment:
        """从 LLM 响应中解析 PlanAdjustment，容错处理。"""
        # 尝试从 markdown code block 中提取 JSON
        text = response.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    data = json.loads(candidate)
                    if isinstance(data, dict):
                        return self._dict_to_adjustment(data)
                except (json.JSONDecodeError, ValueError):
                    continue

        # 直接尝试解析整个响应
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return self._dict_to_adjustment(data)
        except (json.JSONDecodeError, ValueError):
            pass

        logger.warning("无法解析 Adapt 响应，跳过调整: %s", text[:200])
        return PlanAdjustment(reasoning="LLM 响应解析失败，保持原计划")

    def _dict_to_adjustment(self, data: dict) -> PlanAdjustment:
        insert_steps = []
        for item in data.get("insert_steps", []):
            if isinstance(item, dict) and item.get("id"):
                insert_steps.append(Step(
                    id=item["id"],
                    tool=item.get("tool", "python"),
                    description=item.get("description", ""),
                    instruction=item.get("instruction", ""),
                ))
        return PlanAdjustment(
            next_step_adjusted=data.get("next_step_adjusted"),
            insert_steps=insert_steps,
            skip_steps=data.get("skip_steps", []),
            reasoning=data.get("reasoning", ""),
        )

    _KIND_MAP = {
        ".png": "chart", ".jpg": "chart", ".jpeg": "chart", ".svg": "chart",
        ".xlsx": "excel", ".xls": "excel",
        ".csv": "data", ".parquet": "data",
        ".pdf": "report", ".md": "report",
    }

    def _infer_artifact_kind(self, path: str) -> str:
        suffix = Path(path).suffix.lower()
        return self._KIND_MAP.get(suffix, "file")

    def _absolute_output_files(self, workspace: Any) -> list[str]:
        return [
            str((Path(workspace.path) / path).resolve())
            for path in workspace.list_output_files()
        ]

    def _extract_code_block(self, text: str) -> str:
        if "```" not in text:
            return text.strip()
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("python"):
                return candidate.removeprefix("python").strip()
        return parts[1].strip()


def build_orchestrator(config: Any | None = None) -> Orchestrator:
    """Factory: wire up LLM client, tools, and config from defaults."""
    from types import SimpleNamespace

    from app.config import Config
    from app.llm.client import LLMClient
    from app.tools.excel_preprocessor import ExcelPreprocessor
    from app.tools.python_sandbox import PythonSandbox
    from app.tools.result_checker import ResultChecker
    from app.tools.workbook_ingestor import WorkbookIngestor
    from app.tools.profiler import Profiler

    cfg = config or Config()
    llm = LLMClient(
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,
    )
    tools = SimpleNamespace(
        ingestor=WorkbookIngestor(),
        preprocessor=ExcelPreprocessor(),
        profiler=Profiler(),
        sandbox=PythonSandbox(),
        checker=ResultChecker(),
    )
    return Orchestrator(llm_client=llm, tools=tools, config=cfg)
