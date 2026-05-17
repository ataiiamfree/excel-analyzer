import asyncio
from types import SimpleNamespace

from app.agent.orchestrator import Orchestrator, StepResult
from app.agent.plan import ExecutionPlan, Step
from app.context.task_context import TaskContext
from app.tools.result_checker import CheckResult, CheckItem


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
    path = "."

    def __init__(self):
        self.states = []

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
    tools = SimpleNamespace(checker=FakeChecker())
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
