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
from app.tools.result_checker import CheckResult

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
            context.update_workspace_files(workspace.list_files())
            context.update_artifacts(workspace.read_artifact_manifest())
            plan.mark_done(step.id, check=check.status)
            workspace.save_json("plan.json", plan.to_dict())

            # Adaptive: 根据结果动态调整后续计划
            if self._should_adapt(step, result, plan.remaining_steps()):
                adjustment = await self._adapt(context, step, result)
                plan.apply_adjustment(adjustment, current_step_id=step.id)
                workspace.save_json("plan.json", plan.to_dict())

        # 生成报告（有 outline 时分章节 LLM 调用，无 outline 时简单汇总）
        report = await self.reporter.generate(context, workspace)

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
        return TaskResult(report=report, files=workspace.list_output_files())

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

    def _extract_code_block(self, text: str) -> str:
        if "```" not in text:
            return text.strip()
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("python"):
                return candidate.removeprefix("python").strip()
        return parts[1].strip()
