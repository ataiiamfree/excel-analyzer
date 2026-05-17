import pytest

from app.agent.plan import ExecutionPlan, Step
from app.context.prompt_assembler import PromptAssembler, PromptBudgetError
from app.context.task_context import BUDGET_PRESETS, TaskContext


def test_prompt_budget_raises_cleanly_when_no_degradable_section_fits():
    BUDGET_PRESETS["tiny"] = {
        "max_prompt_tokens": 20,
        "step_summaries": 10,
        "max_summary_per_step": 10,
        "max_findings": 1,
        "workspace_files": 1,
    }
    step = Step(id="s1", tool="python", description="x", instruction="x" * 500)
    context = TaskContext(
        task_id="t1",
        user_query="q",
        workbook_manifest={},
        data_profile={},
        budget_preset="tiny",
        plan=ExecutionPlan([step]),
    )

    with pytest.raises(PromptBudgetError):
        PromptAssembler().assemble(context, step)


def test_prompt_budget_compresses_named_summary_section():
    BUDGET_PRESETS["small"] = {
        "max_prompt_tokens": 350,
        "step_summaries": 20,
        "max_summary_per_step": 200,
        "max_findings": 3,
        "workspace_files": 1,
    }
    step = Step(id="s4", tool="python", description="current", instruction="do it")
    context = TaskContext(
        task_id="t1",
        user_query="q",
        workbook_manifest={},
        data_profile={"tables": []},
        budget_preset="small",
        plan=ExecutionPlan(
            [
                Step(id="s1", tool="python", description="1", instruction="1", status="done"),
                Step(id="s2", tool="python", description="2", instruction="2", status="done"),
                Step(id="s3", tool="python", description="3", instruction="3", status="done"),
                step,
            ]
        ),
    )
    context.step_summaries["s1"] = "a" * 100
    context.step_summaries["s2"] = "b" * 100
    context.step_summaries["s3"] = "c" * 100

    prompt = PromptAssembler().assemble(context, step)

    assert "## 当前任务" in prompt
    assert "## 前序步骤结果" in prompt
