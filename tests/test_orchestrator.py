import asyncio
from types import SimpleNamespace

from app.agent.orchestrator import Orchestrator, StepResult
from app.agent.plan import ExecutionPlan, Step
from app.context.task_context import TaskContext


class FakeChecker:
    def validate(self, step, result, context, workspace):
        return SimpleNamespace(status="passed", to_prompt_text=lambda: "passed")


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


class FailingOrchestrator(Orchestrator):
    async def _execute_step(self, step, context, workspace):
        return StepResult(
            stdout="",
            files=[],
            failed=True,
            error="boom",
            retries_exhausted=True,
        )


def test_orchestrator_does_not_mark_failed_step_done():
    step = Step(id="s1", tool="python", description="fail", instruction="fail")
    plan = ExecutionPlan([step])
    context = TaskContext("t1", "q", {}, {}, plan=plan)
    workspace = FakeWorkspace()
    tools = SimpleNamespace(checker=FakeChecker())
    orchestrator = FailingOrchestrator(llm_client=None, tools=tools, config=SimpleNamespace())

    result = asyncio.run(orchestrator.run_plan(plan, context, workspace))

    assert result.report.startswith("任务失败")
    assert plan.get_step("s1").status == "failed"
    assert any(state["status"] == "failed" for state in workspace.states)
