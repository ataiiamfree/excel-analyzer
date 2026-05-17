import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.agent.orchestrator import Orchestrator, StepResult
from app.agent.plan import ExecutionPlan, PlanAdjustment, Step
from app.context.task_context import TaskContext
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
