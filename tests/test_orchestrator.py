import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import openpyxl

from app.agent.orchestrator import Orchestrator, StepResult
from app.agent.plan import ExecutionPlan, PlanAdjustment, Step
from app.context.task_context import TaskContext
from app.session import Session
from app.tools.excel_preprocessor import ExcelPreprocessor
from app.tools.profiler import Profiler
from app.tools.workbook_ingestor import WorkbookIngestor
from app.tools.result_checker import CheckResult, CheckItem
from app.tools.result_checker import ResultChecker


class FakeChecker:
    def __init__(self, status: str = "passed"):
        self._status = status

    def validate(self, step, result, context, workspace):
        return CheckResult(
            step_id=step.id,
            status=self._status,
            checks=[CheckItem("fake", self._status)],
        )


class FakeWorkspace:
    def __init__(self):
        self._tmpdir = tempfile.mkdtemp()
        self.path = self._tmpdir
        self.states = []
        self.artifacts = []

    def is_cancel_requested(self):
        return False

    def write_state(self, **kwargs):
        self.states.append(kwargs)

    def save_json(self, *args, **kwargs):
        pass

    def list_files(self):
        return []

    def read_artifact_manifest(self):
        return []

    def list_output_files(self):
        return []

    def register_artifact(self, **kwargs):
        self.artifacts.append(kwargs)

    def read_text(self, path):
        return ""


class CancelWorkspace(FakeWorkspace):
    def is_cancel_requested(self):
        return True


class FailingOrchestrator(Orchestrator):
    async def _execute_step(self, step, context, workspace):
        return StepResult(
            stdout="",
            files=[],
            failed=True,
            error="boom",
            retries_exhausted=True,
        )


class SuccessOrchestrator(Orchestrator):
    async def _execute_step(self, step, context, workspace):
        return StepResult(stdout="分析完成: 总计 100 行", files=[])


def _make_config():
    return SimpleNamespace(sandbox_timeout=10, max_repair_attempts=1)


def test_orchestrator_does_not_mark_failed_step_done():
    step = Step(id="s1", tool="python", description="fail", instruction="fail")
    plan = ExecutionPlan([step])
    context = TaskContext("t1", "q", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orchestrator = FailingOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orchestrator.run_plan(plan, context, workspace))

    assert result.report == "任务失败，已停止在当前步骤"
    assert plan.get_step("s1").status == "failed"
    assert any(state["status"] == "failed" for state in workspace.states)


def test_orchestrator_cancel():
    step = Step(id="s1", tool="python", description="x", instruction="x")
    plan = ExecutionPlan([step])
    context = TaskContext("t1", "q", {}, {}, plan=plan)
    workspace = CancelWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orchestrator = Orchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orchestrator.run_plan(plan, context, workspace))

    assert result.report == "任务已取消"
    assert plan.get_step("s1").status == "pending"  # 未执行


def test_orchestrator_success_path():
    steps = [
        Step(id="s1", tool="python", description="load", instruction="load"),
        Step(id="s2", tool="python", description="analyze", instruction="analyze"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "q", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orchestrator = SuccessOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orchestrator.run_plan(plan, context, workspace))

    assert plan.get_step("s1").status == "done"
    assert plan.get_step("s2").status == "done"
    assert any(state["status"] == "completed" for state in workspace.states)
    assert len(context.step_summaries) == 2


def test_orchestrator_unknown_tool():
    step = Step(id="s1", tool="unknown_tool", description="x", instruction="x")
    plan = ExecutionPlan([step])
    context = TaskContext("t1", "q", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orchestrator = Orchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orchestrator.run_plan(plan, context, workspace))

    assert plan.get_step("s1").status == "failed"
    assert "未注册的 skill 类型" in plan.get_step("s1").error


# ── Adaptive 测试 ──


def test_should_adapt_returns_false_for_last_step():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    step = Step(id="s1", tool="python", description="x", instruction="x")
    result = StepResult(stdout="ok", files=[])
    assert orch._should_adapt(step, result, remaining_steps=[]) is False


def test_should_adapt_returns_true_for_exploratory():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    step = Step(id="s1", tool="python", description="EDA", instruction="x", is_exploratory=True)
    result = StepResult(stdout="ok", files=[])
    remaining = [Step(id="s2", tool="python", description="y", instruction="y")]
    assert orch._should_adapt(step, result, remaining) is True


def test_should_adapt_returns_true_for_unexpected_findings():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    step = Step(id="s1", tool="python", description="x", instruction="x")
    result = StepResult(stdout="发现异常值: 3个超过阈值", files=[])
    remaining = [Step(id="s2", tool="python", description="y", instruction="y")]
    assert orch._should_adapt(step, result, remaining) is True


def test_should_adapt_returns_false_for_normal_result():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    step = Step(id="s1", tool="python", description="x", instruction="x")
    result = StepResult(stdout="处理完成，共 100 行", files=[])
    remaining = [Step(id="s2", tool="python", description="y", instruction="y")]
    assert orch._should_adapt(step, result, remaining) is False


def test_parse_adjustment_from_json():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    response = json.dumps({
        "next_step_adjusted": "用 98 天作为阈值",
        "insert_steps": [
            {"id": "s1b", "tool": "python", "description": "深入分析", "instruction": "分析异常项"}
        ],
        "skip_steps": ["s3"],
        "reasoning": "发现合理阈值为 98 天",
    })
    adj = orch._parse_adjustment(response)
    assert adj.next_step_adjusted == "用 98 天作为阈值"
    assert len(adj.insert_steps) == 1
    assert adj.insert_steps[0].id == "s1b"
    assert adj.skip_steps == ["s3"]


def test_parse_adjustment_from_code_block():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    response = '```json\n{"next_step_adjusted": null, "insert_steps": [], "skip_steps": [], "reasoning": "无需调整"}\n```'
    adj = orch._parse_adjustment(response)
    assert adj.next_step_adjusted is None
    assert adj.insert_steps == []
    assert adj.reasoning == "无需调整"


def test_parse_adjustment_invalid_json_returns_noop():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    adj = orch._parse_adjustment("这不是 JSON")
    assert adj.insert_steps == []
    assert adj.skip_steps == []
    assert "解析失败" in adj.reasoning


class AdaptOrchestrator(Orchestrator):
    """模拟：s1 返回含"发现"的结果触发 Adapt，Adapt 插入一个新步骤。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._step_count = 0

    async def _execute_step(self, step, context, workspace):
        self._step_count += 1
        if step.id == "s1":
            return StepResult(stdout="发现平均时长 42 天，标准差 28 天", files=[])
        return StepResult(stdout="处理完成", files=[])

    async def _adapt(self, context, step, result):
        # 模拟 LLM 返回：插入一个新步骤
        return PlanAdjustment(
            insert_steps=[Step(
                id="s1_deep",
                tool="python",
                description="深入分析异常",
                instruction="用 98 天阈值筛选异常项",
            )],
            reasoning="发现阈值应为 98 天",
        )


def test_orchestrator_adapt_inserts_step():
    steps = [
        Step(id="s1", tool="python", description="统计", instruction="统计", is_exploratory=True),
        Step(id="s2", tool="python", description="报告", instruction="报告"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析采购时长", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orch = AdaptOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orch.run_plan(plan, context, workspace))

    # s1 完成后应该插入了 s1_deep，然后执行 s1_deep 和 s2
    assert plan.get_step("s1").status == "done"
    assert plan.get_step("s1_deep") is not None
    assert plan.get_step("s1_deep").status == "done"
    assert plan.get_step("s2").status == "done"
    assert orch._step_count == 3  # s1, s1_deep, s2


# ── Reporter 集成测试 ──


def test_success_path_report_is_nonempty():
    """成功路径下 TaskResult.report 应为非空 Markdown。"""
    steps = [
        Step(id="s1", tool="python", description="统计", instruction="统计"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orch = SuccessOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orch.run_plan(plan, context, workspace))

    assert result.report  # 非空
    assert "分析" in result.report


def test_success_path_saves_report_file():
    """成功路径下应将报告保存到 output/report.md。"""
    steps = [
        Step(id="s1", tool="python", description="load", instruction="load"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orch = SuccessOrchestrator(llm_client=None, tools=tools, config=_make_config())

    asyncio.run(orch.run_plan(plan, context, workspace))

    report_path = Path(workspace.path) / "output" / "report.md"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert len(content) > 0


def test_success_path_registers_report_artifact():
    """成功路径下应将 report 注册到 artifact_manifest。"""
    steps = [
        Step(id="s1", tool="python", description="load", instruction="load"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orch = SuccessOrchestrator(llm_client=None, tools=tools, config=_make_config())

    asyncio.run(orch.run_plan(plan, context, workspace))

    assert any(a.get("kind") == "report" for a in workspace.artifacts)


def test_report_without_outline_uses_simple_response():
    """没有 report_outline 时，Reporter 使用 simple response（无 LLM 调用）。"""
    steps = [
        Step(id="s1", tool="python", description="统计", instruction="统计"),
    ]
    plan = ExecutionPlan(steps)  # 无 report_outline
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orch = SuccessOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orch.run_plan(plan, context, workspace))

    assert "# 分析结果" in result.report
    assert "分析完成" in result.report  # step summary 被包含


class BrokenLLMReporterOrchestrator(SuccessOrchestrator):
    """Reporter 的 LLM 调用会抛异常，用于测试 fallback。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        class ExplodingLLM:
            async def call(self, prompt, max_tokens=2000):
                raise RuntimeError("LLM 连接超时")

        from app.agent.reporter import Reporter
        self.reporter = Reporter(llm_client=ExplodingLLM())


def test_reporter_failure_falls_back_to_simple_response():
    """Reporter LLM 调用失败时，应降级为 simple response 而非崩溃。"""
    steps = [
        Step(id="s1", tool="python", description="统计", instruction="统计"),
    ]
    plan = ExecutionPlan(
        steps,
        report_outline=[
            {"title": "分析总览", "related_steps": ["s1"], "word_count": 500},
        ],
    )
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=ResultChecker())
    orch = BrokenLLMReporterOrchestrator(llm_client=None, tools=tools, config=_make_config())

    result = asyncio.run(orch.run_plan(plan, context, workspace))

    # 没有崩溃，降级为 simple response
    assert result.report
    assert "# 分析结果" in result.report
    assert any(state["status"] == "completed" for state in workspace.states)


# ── 产物自动注册测试 ──


class OutputFilesOrchestrator(Orchestrator):
    """步骤返回 output_files，用于测试自动注册。"""

    async def _execute_step(self, step, context, workspace):
        return StepResult(
            stdout="生成图表完成",
            files=["output/趋势图.png", "output/汇总.xlsx", "output/data.csv"],
        )


def test_output_files_auto_registered_as_artifacts():
    """步骤产出文件应自动注册到 artifact_manifest。"""
    steps = [
        Step(id="s1", tool="python", description="生成图表", instruction="画图"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析数据", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orch = OutputFilesOrchestrator(llm_client=None, tools=tools, config=_make_config())

    asyncio.run(orch.run_plan(plan, context, workspace))

    # 3 个步骤产物 + 1 个 report 产物 = 4
    assert len(workspace.artifacts) == 4
    kinds = {a["kind"] for a in workspace.artifacts}
    assert "chart" in kinds
    assert "excel" in kinds
    assert "data" in kinds
    # 每个产物的 producer_step 应为步骤 id
    step_artifacts = [a for a in workspace.artifacts if a.get("producer_step") == "s1"]
    assert len(step_artifacts) == 3


def test_infer_artifact_kind():
    """文件后缀应正确映射到 artifact kind。"""
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    assert orch._infer_artifact_kind("output/chart.png") == "chart"
    assert orch._infer_artifact_kind("output/chart.jpg") == "chart"
    assert orch._infer_artifact_kind("output/result.xlsx") == "excel"
    assert orch._infer_artifact_kind("output/export.csv") == "data"
    assert orch._infer_artifact_kind("output/report.md") == "report"
    assert orch._infer_artifact_kind("output/unknown.zip") == "file"


# ── Plan 解析测试 ──


def test_parse_plan_from_json():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    response = json.dumps({
        "steps": [
            {"id": "s1", "tool": "python", "description": "加载数据", "instruction": "读取Excel"},
            {"id": "s2", "tool": "python", "description": "统计", "instruction": "统计分析", "depends_on": ["s1"]},
        ],
        "report_outline": [
            {"title": "数据总览", "related_steps": ["s1", "s2"], "word_count": 800},
        ],
    })
    plan = orch._parse_plan(response)
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "s1"
    assert plan.steps[1].depends_on == ["s1"]
    assert len(plan.report_outline) == 1


def test_parse_plan_from_code_block():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    response = '```json\n{"steps": [{"id": "s1", "tool": "python", "description": "x", "instruction": "y"}], "report_outline": []}\n```'
    plan = orch._parse_plan(response)
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "s1"


def test_parse_plan_fallback_on_invalid_json():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    plan = orch._parse_plan("这不是有效的 JSON 响应", fallback_instruction="统计销售额")
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "s1"
    assert plan.steps[0].instruction == "统计销售额"
    assert plan.steps[0].is_exploratory is True


def test_plan_falls_back_when_llm_call_fails():
    class EmptyLLM:
        async def call(self, prompt, max_tokens=2000, temperature=0.1, thinking=None):
            raise RuntimeError("LLM 响应为空")

    session = Session.create(file_path="input.xlsx")
    context = TaskContext("t1", "统计库存健康", {}, {})
    orch = Orchestrator(llm_client=EmptyLLM(), tools=None, config=_make_config())

    plan = asyncio.run(orch._plan(context, session))

    assert len(plan.steps) == 1
    assert plan.steps[0].instruction == "统计库存健康"


def test_parse_plan_extracts_json_from_chatty_response():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())
    response = '我先分析一下。\n{"steps": [{"id": "s1", "tool": "python", "description": "x", "instruction": "y"}]}\n完成。'

    plan = orch._parse_plan(response)

    assert len(plan.steps) == 1
    assert plan.steps[0].instruction == "y"


def test_extract_code_block_rejects_json_plan_as_python():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())

    code = orch._extract_code_block('{"plan": [{"step": 1, "description": "do work"}]}')

    assert "LLM did not return executable Python code" in code


def test_extract_code_block_rejects_empty_response_as_python():
    orch = Orchestrator(llm_client=None, tools=None, config=_make_config())

    code = orch._extract_code_block("")

    assert "LLM returned an empty response" in code


def test_execute_step_catches_executor_exception():
    class ExplodingOrchestrator(Orchestrator):
        async def _execute_python(self, step, context, workspace):
            raise RuntimeError("LLM 响应为空")

    step = Step(id="s1", tool="python", description="x", instruction="x")
    context = TaskContext("t1", "q", {}, {})
    workspace = FakeWorkspace()
    orch = ExplodingOrchestrator(
        llm_client=None,
        tools=SimpleNamespace(checker=FakeChecker()),
        config=_make_config(),
    )

    result = asyncio.run(orch._execute_step(step, context, workspace))

    assert result.failed is True
    assert result.retries_exhausted is True
    assert "LLM 响应为空" in result.error


def test_step_callbacks_called():
    """on_step_start 和 on_step_end 回调应被调用。"""
    started = []
    ended = []

    class CallbackOrchestrator(SuccessOrchestrator):
        pass

    steps = [
        Step(id="s1", tool="python", description="统计", instruction="统计"),
    ]
    plan = ExecutionPlan(steps)
    context = TaskContext("t1", "分析", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orch = CallbackOrchestrator(llm_client=None, tools=tools, config=_make_config())

    async def on_start(step):
        started.append(step.id)

    async def on_end(step, result):
        ended.append(step.id)

    orch._on_step_start = on_start
    orch._on_step_end = on_end

    asyncio.run(orch.run_plan(plan, context, workspace))

    assert started == ["s1"]
    assert ended == ["s1"]


def test_run_first_analysis_preprocesses_into_workspace(tmp_path):
    """Full run smoke: first analysis should preprocess and cache profile."""
    workbook_path = tmp_path / "input.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["名称", "金额"])
    ws.append(["A", 10])
    ws.append(["B", 20])
    workbook.save(workbook_path)

    class PlanningLLM:
        async def call(self, prompt, max_tokens=2000, temperature=0.1, thinking=None):
            return '{"steps": [], "report_outline": []}'

    config = SimpleNamespace(
        workspace_dir=str(tmp_path / "workspace"),
        budget_preset="deepseek",
        sandbox_timeout=10,
        max_repair_attempts=1,
    )
    tools = SimpleNamespace(
        ingestor=WorkbookIngestor(),
        preprocessor=ExcelPreprocessor(),
        profiler=Profiler(),
        checker=ResultChecker(),
    )
    session = Session.create(file_path=str(workbook_path))
    orch = Orchestrator(llm_client=PlanningLLM(), tools=tools, config=config)

    result = asyncio.run(orch.run("分析金额", session))

    assert result.report.startswith("# 分析结果")
    assert session.profile is not None
    assert session.normalized_dir is not None
    assert Path(session.normalized_dir).is_absolute()
    assert Path(session.normalized_dir).exists()
    assert session.is_follow_up
