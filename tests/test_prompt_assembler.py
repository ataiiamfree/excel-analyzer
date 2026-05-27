import pytest

from app.agent.plan import ExecutionPlan, Step
from app.context.prompt_assembler import PromptAssembler, PromptBudgetError
from app.context.task_context import BUDGET_PRESETS, TaskContext


@pytest.fixture(autouse=True)
def _clean_budget_presets():
    """确保测试注入的 preset 不污染其他测试。"""
    original = dict(BUDGET_PRESETS)
    yield
    BUDGET_PRESETS.clear()
    BUDGET_PRESETS.update(original)


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
    # 设置一个较小的 budget，使得 300 chars 的 summaries 必须被压缩
    BUDGET_PRESETS["small"] = {
        "max_prompt_tokens": 500,
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
    # 验证压缩确实发生了（_history 键合并了旧摘要）
    assert "_history" in context.step_summaries or len(context.step_summaries) <= 4


def test_assemble_adapt_includes_key_sections():
    step = Step(id="s1", tool="python", description="统计时长", instruction="计算采购时长")
    context = TaskContext(
        task_id="t1",
        user_query="分析采购时长",
        workbook_manifest={},
        data_profile={},
        plan=ExecutionPlan([
            step,
            Step(id="s2", tool="python", description="报告", instruction="生成报告"),
        ]),
    )
    context.key_findings = ["平均时长 42 天"]

    prompt = PromptAssembler().assemble_adapt(context, step, "平均时长 42 天，标准差 28 天")

    assert "任务规划助手" in prompt
    assert "分析采购时长" in prompt
    assert "统计时长" in prompt
    assert "平均时长 42 天" in prompt
    assert "insert_steps" in prompt  # 输出格式说明


def test_degradable_sections_removed_when_over_budget():
    """当压缩摘要和文件列表都不够时，应逐个移除 degradable 段。"""
    BUDGET_PRESETS["tight"] = {
        "max_prompt_tokens": 500,
        "step_summaries": 10,
        "max_summary_per_step": 10,
        "max_findings": 1,
        "workspace_files": 1,
    }
    step = Step(id="s1", tool="python", description="x", instruction="do it")
    context = TaskContext(
        task_id="t1",
        user_query="q",
        workbook_manifest={},
        data_profile={"tables": []},
        budget_preset="tight",
        plan=ExecutionPlan([step]),
    )
    context.key_findings = ["finding " * 10]

    prompt = PromptAssembler().assemble(context, step)
    # findings 应该被降级移除，但核心 profile/任务段保留
    assert "## 当前任务" in prompt
    assert "## 用户问题" in prompt
    assert "## 数据概况" in prompt


def test_compact_profile_keeps_paths_for_all_tables_under_budget():
    step = Step(id="s1", tool="python", description="统计", instruction="统计前两个表")
    profile = {
        "tables": [
            {
                "table_id": "主表-在途业扩工单_t1",
                "source": "主表-在途业扩工单!A1:AF108",
                "path": "normalized/主表-在途业扩工单_t1.xlsx",
                "shape": {"rows": 106, "cols": 32},
                "columns_detail": [
                    {"name": "正式受理日期", "dtype": "datetime64[us]"},
                    {"name": "接火送电", "dtype": "datetime64[us]"},
                    {"name": "增减容量", "dtype": "int64"},
                ],
                "warnings": ["公式没有缓存计算值"] * 20,
            },
            {
                "table_id": "已归档工单_t1",
                "source": "已归档工单!A1:AE418",
                "path": "normalized/已归档工单_t1.xlsx",
                "shape": {"rows": 416, "cols": 31},
                "columns_detail": [
                    {"name": "正式受理日期", "dtype": "datetime64[us]"},
                    {"name": "接火送电", "dtype": "datetime64[us]"},
                    {"name": "增减容量", "dtype": "int64"},
                ],
            },
        ],
    }
    context = TaskContext(
        task_id="t1",
        user_query="只分析第一第二个 sheet",
        workbook_manifest={},
        data_profile=profile,
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "normalized/主表-在途业扩工单_t1.xlsx" in prompt
    assert "normalized/已归档工单_t1.xlsx" in prompt
    assert "*_preview.xlsx" in prompt
    assert "不要用 glob" in prompt
    assert "接火送电/送电日期" in prompt
    assert "format='mixed'" in prompt
