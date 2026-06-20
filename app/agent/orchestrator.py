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


_FULL_REPORT_KEYWORDS = (
    "报告",
    "分析报告",
    "完整分析",
    "详细分析",
    "深度分析",
    "专题分析",
    "汇报材料",
    "总结材料",
    "写一篇",
    "撰写",
    "word",
    "不少于",
)
_NO_REPORT_KEYWORDS = (
    "不要报告",
    "不需要报告",
    "无需报告",
    "简单说",
    "简单分析",
    "一两句",
    "两句话",
)


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
    failed: bool = False
    failed_step_description: str = ""
    error_summary: str = ""


StepStartCallback = Callable[[Step, int, int], Awaitable[None]]
StepEndCallback = Callable[[Step, StepResult], Awaitable[None]]
PlanReadyCallback = Callable[[ExecutionPlan], Awaitable[None]]
TokenCallback = Callable[[str], Awaitable[None]]
Executor = Callable[[Step, TaskContext, Any, TokenCallback | None], Awaitable[StepResult]]


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
        on_step_start: StepStartCallback | None = None,
        on_step_end: StepEndCallback | None = None,
        on_plan_ready: PlanReadyCallback | None = None,
        on_report_token: TokenCallback | None = None,
        on_reasoning_token: TokenCallback | None = None,
    ) -> TaskResult:
        """Full pipeline: Ingest → Preprocess → Profile → Plan → Execute → Report.

        On follow-ups (session.is_follow_up), skips Ingest/Preprocess/Profile
        and reuses cached session data.
        """
        if session.is_follow_up and session.profile is not None:
            # 追问：复用首次分析的 workspace（数据文件在那里）
            first_task_id = session.tasks[0] if session.tasks else None
            workspace = Workspace(root=self.config.workspace_dir, task_id=first_task_id)
            logger.info("追问模式，复用 workspace %s", workspace.task_id)
            manifest = session.workbook_manifest or {}
            profile = session.profile
        else:
            # 首次分析：新 workspace + 全流程
            workspace = Workspace(root=self.config.workspace_dir)
            logger.info("首次分析，开始全流程: Ingest → Preprocess → Profile → Plan → Execute → Report")
            raw_file_path = Path(workspace.save_upload(session.file_path)).resolve()
            logger.info("文件已复制到 workspace: %s", raw_file_path)

            normalized_dir = (Path(workspace.path) / "normalized").resolve()
            manifest = self.tools.ingestor.scan(raw_file_path)
            logger.info("Ingest 完成, sheets=%s", list(manifest.keys()) if isinstance(manifest, dict) else "N/A")

            preprocess_result = self.tools.preprocessor.process(
                file_path=raw_file_path,
                manifest=manifest,
                output_dir=normalized_dir,
            )
            tables = preprocess_result.tables
            logger.info("Preprocess 完成, 表数=%d", len(tables))

            workspace.save_artifacts(tables)
            profile = self.tools.profiler.profile(tables)
            logger.info("Profile 完成, 表数=%d", len(profile) if isinstance(profile, (dict, list)) else 0)

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

        # LLM 规划（_plan 内部已有 fallback，不会抛异常）
        logger.info("开始 LLM 规划...")
        plan = await self._plan(context, session)
        logger.info("规划完成, steps=%d, outline=%d",
                     len(plan.steps), len(plan.report_outline) if plan.report_outline else 0)
        for s in plan.steps:
            logger.info("  Step %s [%s]: %s", s.id, s.tool, s.description)
        workspace.save_json("plan.json", plan.to_dict())
        if on_plan_ready:
            await on_plan_ready(plan)

        # 执行
        result = await self.run_plan(
            plan,
            context,
            workspace,
            on_step_start=on_step_start,
            on_step_end=on_step_end,
            on_report_token=on_report_token,
            on_reasoning_token=on_reasoning_token,
        )

        # 更新 session（含结果摘要，供追问使用）
        session.update_after_task(
            task_id=workspace.task_id,
            findings=context.key_findings,
            summary_text=query,
            result_summary=result.report[:500] if result.report else "",
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
            "你是数据分析规划器。根据用户需求和数据概况，输出 JSON 格式的执行计划。\n"
            "只输出一个 JSON 对象，不要解释，不要输出思考过程，不要输出 markdown。\n\n"
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
            "普通统计、筛选、排名、导出结果表、生成图表的问题，report_outline 必须返回 []；"
            "最终由系统展示表格/图表并给一两句简短结论。\n"
            "普通 Excel 分析任务默认只生成 1 个 python 步骤，一次性完成读取、清洗、计算和导出；"
            "不要把读取数据、清洗、计算、导出拆成多个 python 步骤。\n"
            "只有用户明确要求完整长报告，或任务必须先探索再决策时，才生成多个步骤；"
            "即使复杂数据分析，也优先用 1 个 python 步骤完成。\n"
            "只有当用户明确要求“报告、分析报告、详细分析、汇报材料、长文”等完整写作产物时，"
            "才生成 report_outline。\n"
            "不要在 instruction 中硬编码 normalized 文件的绝对路径；只描述要使用哪张表和哪些字段，"
            "代码生成阶段会根据数据概况里的 tables[].path 读取正式数据文件。\n"
            "如果用户要求导出、保存、输出结果表，计划必须明确要求把用户可见产物写入 output/ 目录。\n"
        )

        try:
            # 规划调用关闭思考模式：输出是结构化 JSON，不需要深度推理
            response = await self.llm.call(prompt, max_tokens=4000, thinking=False)
        except Exception as exc:
            logger.warning("LLM 规划调用失败，使用默认单步计划: %s", exc)
            return ExecutionPlan(steps=[
                Step(
                    id="s1",
                    tool="python",
                    description="分析数据",
                    instruction=context.user_query or "根据用户需求完成数据分析并输出结果。",
                    is_exploratory=True,
                )
            ])
        return self._parse_plan(response, fallback_instruction=context.user_query)

    def _parse_plan(self, response: str, fallback_instruction: str = "") -> ExecutionPlan:
        """Parse LLM response into an ExecutionPlan with fallback."""
        text = response.strip()

        for candidate in self._json_candidates(text):
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(data, dict) and ("steps" in data or "plan" in data):
                return self._dict_to_plan(data, user_query=fallback_instruction)

        # Fallback: single generic step
        logger.warning("无法解析 Plan 响应，使用默认单步计划")
        return ExecutionPlan(steps=[
            Step(
                id="s1",
                tool="python",
                description="分析数据",
                instruction=fallback_instruction or "根据用户需求完成数据分析并输出结果。",
                is_exploratory=True,
            ),
        ])

    def _json_candidates(self, text: str) -> list[str]:
        """Return likely JSON payloads from a chatty LLM response."""
        candidates: list[str] = []
        stripped = text.strip()
        if stripped:
            candidates.append(stripped)

        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate:
                    candidates.append(candidate)

        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last > first:
            candidates.append(text[first : last + 1].strip())

        seen: set[str] = set()
        unique = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    def _dict_to_plan(self, data: dict, user_query: str = "") -> ExecutionPlan:
        if "steps" not in data and isinstance(data.get("plan"), list):
            plan_items = data.get("plan") or []
            instruction_parts = []
            for item in plan_items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("step") or "").strip()
                description = str(item.get("description") or "").strip()
                line = "：".join(part for part in (name, description) if part)
                if line:
                    instruction_parts.append(line)
            if instruction_parts:
                return ExecutionPlan(steps=[
                    Step(
                        id="s1",
                        tool="python",
                        description="按规划完成数据分析",
                        instruction="\n".join(instruction_parts),
                        is_exploratory=False,
                    )
                ], report_outline=self._report_outline_for_query(data, user_query))

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
        outline = self._report_outline_for_query(data, user_query)
        steps = self._collapse_result_steps_if_needed(steps, user_query, outline)
        return ExecutionPlan(steps=steps, report_outline=outline)

    def _collapse_result_steps_if_needed(
        self,
        steps: list[Step],
        user_query: str,
        outline: list[dict[str, Any]],
    ) -> list[Step]:
        if len(steps) <= 2 or outline or self._wants_full_report(user_query):
            return steps
        if any(step.tool != "python" for step in steps):
            return steps

        combined = "\n".join(
            f"{index + 1}. {step.description or step.instruction}: {step.instruction}"
            for index, step in enumerate(steps)
        )
        logger.info("普通结果型任务 planner 返回 %d 个 python 步骤，合并为单步执行", len(steps))
        return [
            Step(
                id="s1",
                tool="python",
                description="完成数据分析并输出结果",
                instruction=(
                    f"{user_query or '根据用户需求完成数据分析并输出结果。'}\n\n"
                    "请在一个 Python 脚本中一次性完成以下子任务，并把用户可见产物写入 output/ 目录：\n"
                    f"{combined}"
                ),
                is_exploratory=True,
            )
        ]

    def _report_outline_for_query(self, data: dict, user_query: str = "") -> list[dict[str, Any]]:
        outline = data.get("report_outline", [])
        if not isinstance(outline, list):
            return []
        if user_query and outline and not self._wants_full_report(user_query):
            logger.info("用户未要求完整报告，忽略 planner 返回的 report_outline")
            return []
        return [item for item in outline if isinstance(item, dict)]

    def _wants_full_report(self, query: str) -> bool:
        normalized = "".join((query or "").lower().split())
        if any(keyword in normalized for keyword in _NO_REPORT_KEYWORDS):
            return False
        return any(keyword in normalized for keyword in _FULL_REPORT_KEYWORDS)

    async def run_plan(
        self,
        plan: ExecutionPlan,
        context: TaskContext,
        workspace: Any,
        *,
        on_step_start: StepStartCallback | None = None,
        on_step_end: StepEndCallback | None = None,
        on_report_token: TokenCallback | None = None,
        on_reasoning_token: TokenCallback | None = None,
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
            step_index = plan.steps.index(step) + 1
            total_steps = len(plan.steps)
            logger.info("▶ 执行 Step %s [%d/%d] [%s]: %s", step.id, step_index, total_steps, step.tool, step.description)

            if on_step_start:
                await on_step_start(step, step_index, total_steps)

            result = await self._execute_step(step, context, workspace, on_reasoning_token)
            check = self.tools.checker.validate(step, result, context, workspace)

            if check.status == "failed" and not result.retries_exhausted:
                result = await self._repair_from_check(
                    step,
                    result,
                    check,
                    context,
                    workspace,
                    on_reasoning_token,
                )
                check = self.tools.checker.validate(step, result, context, workspace)

            if result.failed or check.status == "failed":
                logger.error("✗ Step %s 失败: %s", step.id, (result.error or check.to_prompt_text())[:200])
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
                error_detail = result.error or check.to_prompt_text()
                return TaskResult(
                    report="任务失败，已停止在当前步骤",
                    files=[],
                    failed=True,
                    failed_step_description=step.description,
                    error_summary=error_detail[:300],
                )

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

            logger.info("✓ Step %s 完成, 产出文件=%d, stdout=%d chars",
                        step.id, len(result.output_files), len(result.stdout or ""))
            context.update_workspace_files(workspace.list_files())
            context.update_artifacts(workspace.read_artifact_manifest())
            plan.mark_done(step.id, check=check.status)
            workspace.save_json("plan.json", plan.to_dict())

            if on_step_end:
                await on_step_end(step, result)

            # Adaptive: 根据结果动态调整后续计划
            if self._should_adapt(step, result, plan.remaining_steps()):
                adjustment = await self._adapt(context, step, result)
                plan.apply_adjustment(adjustment, current_step_id=step.id)
                workspace.save_json("plan.json", plan.to_dict())

        # 生成报告（有 outline 时分章节 LLM 调用，无 outline 时简单汇总）
        logger.info("所有步骤执行完毕，开始生成报告...")
        try:
            report = await self.reporter.generate(
                context,
                workspace,
                stream_callback=on_report_token,
                reasoning_callback=on_reasoning_token,
            )
            logger.info("报告生成完成, 长度=%d chars", len(report))
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

    async def _execute_step(
        self,
        step: Step,
        context: TaskContext,
        workspace: Any,
        reasoning_callback: TokenCallback | None = None,
    ) -> StepResult:
        executor = self.executors.get(step.tool)
        if executor is None:
            return StepResult(
                stdout="",
                files=[],
                failed=True,
                error=f"未注册的 skill 类型: {step.tool}",
                retries_exhausted=True,
            )
        try:
            return await executor(step, context, workspace, reasoning_callback)
        except Exception as exc:
            logger.exception("步骤执行异常: %s", step.id)
            return StepResult(
                stdout="",
                files=[],
                failed=True,
                error=f"{type(exc).__name__}: {exc}",
                retries_exhausted=True,
            )

    async def _execute_knowledge(
        self,
        step: Step,
        context: TaskContext,
        workspace: Any,
        reasoning_callback: TokenCallback | None = None,
    ) -> StepResult:
        chunks = self.tools.knowledge.search(step.instruction, top_k=3)
        return StepResult(stdout=str(chunks), files=[])

    async def _execute_python(
        self,
        step: Step,
        context: TaskContext,
        workspace: Any,
        reasoning_callback: TokenCallback | None = None,
    ) -> StepResult:
        prompt = self.assembler.assemble(context, step)
        code_response = await self.llm.call(
            prompt,
            max_tokens=16000,
            reasoning_callback=reasoning_callback,
        )
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
            code = self._extract_code_block(
                await self.llm.call(repair_prompt, reasoning_callback=reasoning_callback)
            )
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
        reasoning_callback: TokenCallback | None = None,
    ) -> StepResult:
        script_text = workspace.read_text(result.script_path) if result.script_path else ""
        repair_prompt = self.assembler.assemble_repair(
            context,
            step,
            failed_code=script_text,
            stderr=result.error,
            check_report=check.to_prompt_text(),
        )
        code = self._extract_code_block(
            await self.llm.call(repair_prompt, reasoning_callback=reasoning_callback)
        )
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
        response = await self.llm.call(prompt, max_tokens=2000, thinking=False)
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
            stripped = text.strip()
            if not stripped:
                return "raise RuntimeError('LLM returned an empty response instead of Python code.')"
            if stripped.startswith(("{", "[")):
                return (
                    "raise RuntimeError("
                    "'LLM did not return executable Python code; response looked like JSON or a plan.'"
                    ")"
                )
            return stripped
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("python"):
                code = candidate.removeprefix("python").strip()
                return code or "raise RuntimeError('LLM returned an empty Python code block.')"
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
        thinking=cfg.llm_thinking,
        effort=cfg.llm_reasoning_effort,
        timeout=cfg.llm_timeout_seconds,
    )
    tools = SimpleNamespace(
        ingestor=WorkbookIngestor(),
        preprocessor=ExcelPreprocessor(),
        profiler=Profiler(),
        sandbox=PythonSandbox(),
        checker=ResultChecker(),
    )
    return Orchestrator(llm_client=llm, tools=tools, config=cfg)
