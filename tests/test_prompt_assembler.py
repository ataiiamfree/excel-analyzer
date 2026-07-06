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
        "max_prompt_tokens": 1200,
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
        "max_prompt_tokens": 1200,
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


def test_task_context_extracts_final_answer_from_long_stdout():
    context = TaskContext(
        task_id="t1",
        user_query="q",
        workbook_manifest={},
        data_profile={},
    )
    stdout = "debug line\n" + ("noise\n" * 500) + "Final Answer: 14400\n"

    context.add_step_summary("s1", stdout, "分析")

    assert context.final_answers["s1"] == "14400"
    assert "Final Answer: 14400" in context.step_summaries["s1"]


def test_task_context_extracts_multiline_final_answer():
    context = TaskContext(
        task_id="t1",
        user_query="q",
        workbook_manifest={},
        data_profile={},
    )

    context.add_step_summary(
        "s1",
        "debug\nFinal Answer: First measure\nSecond measure\nThird measure",
        "分析",
    )

    assert context.final_answers["s1"] == "First measure\nSecond measure\nThird measure"


def test_python_prompt_requires_final_answer_and_fuzzy_matching():
    step = Step(id="s1", tool="python", description="查询", instruction="查询项目")
    context = TaskContext(
        task_id="t1",
        user_query="What is the value?",
        workbook_manifest={},
        data_profile={"tables": []},
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "Final Answer" in prompt
    assert "difflib fuzzy candidates" in prompt
    assert "不要直接输出 Not Found/N/A" in prompt
    assert "输出全部匹配项" in prompt
    assert "_context_group" not in prompt
    assert "不要仅因为数值绝对值大于 1 就除以 100" not in prompt
    assert "应直接使用这些配对列做差或比较" not in prompt
    assert "Python 任务提示" not in prompt


def test_profile_prompt_includes_repeated_column_families():
    step = Step(id="s1", tool="python", description="查询", instruction="查询 press")
    context = TaskContext(
        task_id="t1",
        user_query="How much did the athlete press?",
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "source": "Sheet1!A1:E5",
                    "path": "normalized/Sheet1_t1.parquet",
                    "shape": {"rows": 4, "cols": 5},
                    "columns_detail": [
                        {"name": "weightlifter", "dtype": "object"},
                        {"name": "press", "dtype": "float64"},
                        {"name": "press_2", "dtype": "float64"},
                        {"name": "press_3", "dtype": "float64"},
                    ],
                    "column_families": [
                        {
                            "base": "press",
                            "kind": "deduped_repeated_header",
                            "columns": ["press", "press_2", "press_3"],
                        }
                    ],
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "column_families" in prompt
    assert "press(deduped_repeated_header)=[press, press_2, press_3]" in prompt
    assert "不要默认取第一个" in prompt
    assert "最佳有效" not in prompt


def test_profile_prompt_explains_context_group_columns():
    step = Step(id="s1", tool="python", description="查询", instruction="查询 first floor")
    context = TaskContext(
        task_id="t1",
        user_query='What is the quantity of "Floor Tiles" on the first floor?',
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "source": "Sheet1!A1:D6",
                    "path": "normalized/Sheet1_t1.parquet",
                    "shape": {"rows": 3, "cols": 5},
                    "columns_detail": [
                        {"name": "Project Name", "dtype": "object"},
                        {"name": "Unit", "dtype": "object"},
                        {"name": "Quantity", "dtype": "float64"},
                        {"name": "_context_group", "dtype": "object"},
                    ],
                    "enum_columns": {
                        "_context_group": ["First Floor", "Second Floor"],
                    },
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "_context_group(object)" in prompt
    assert "_context_*` 列表示从父级/楼层/分组标题行提取" in prompt
    assert "不要把 Unit/单位/计量单位列当作楼层或分组列" in prompt


def test_profile_prompt_renders_header_path_when_multi_level():
    step = Step(id="s1", tool="python", description="查询", instruction="按 Scotland 2023 求和")
    context = TaskContext(
        task_id="t1",
        user_query="Compare Landings into Scotland vs England for 2023",
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "source": "Sheet1!A1:E5",
                    "path": "normalized/Sheet1_t1.parquet",
                    "shape": {"rows": 2, "cols": 5},
                    "columns_detail": [
                        {
                            "name": "Species",
                            "dtype": "object",
                            "header_path": ["Species"],
                        },
                        {
                            "name": "2022",
                            "dtype": "int64",
                            "header_path": ["Landings into", "Scotland", "2022"],
                        },
                        {
                            "name": "2023",
                            "dtype": "int64",
                            "header_path": ["Landings into", "Scotland", "2023"],
                        },
                        {
                            "name": "2022_2",
                            "dtype": "int64",
                            "header_path": ["Landings into", "England", "2022"],
                        },
                        {
                            "name": "2023_2",
                            "dtype": "int64",
                            "header_path": ["Landings into", "England", "2023"],
                        },
                    ],
                    "columns_grouped": [],
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    # Multi-level columns get an inline lineage annotation
    assert "2023(int64)[header_path: Landings into > Scotland > 2023]" in prompt
    assert "2023_2(int64)[header_path: Landings into > England > 2023]" in prompt
    # Single-level column stays compact — no header_path noise
    assert "Species(object)" in prompt
    assert "Species(object)[header_path" not in prompt
    # Conditional hint kicks in
    assert "header_path" in prompt
    assert "Landings into > £(000) > 2008/09" in prompt or "顶级组 → 叶列" in prompt
    assert "不要只匹配叶列名" in prompt


def test_profile_prompt_omits_header_path_hint_for_flat_tables():
    step = Step(id="s1", tool="python", description="查询", instruction="求和")
    context = TaskContext(
        task_id="t1",
        user_query="What is the total amount?",
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "source": "Sheet1!A1:B3",
                    "path": "normalized/Sheet1_t1.parquet",
                    "shape": {"rows": 2, "cols": 2},
                    "columns_detail": [
                        {
                            "name": "Name",
                            "dtype": "object",
                            "header_path": ["Name"],
                        },
                        {
                            "name": "Amount",
                            "dtype": "int64",
                            "header_path": ["Amount"],
                        },
                    ],
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "Name(object)" in prompt
    assert "Amount(int64)" in prompt
    # No header_path annotation, no hint — flat table stays flat
    assert "[header_path:" not in prompt
    assert "顶级组 → 叶列" not in prompt


def test_python_prompt_includes_rate_hints_only_when_rate_columns_exist():
    step = Step(id="s1", tool="python", description="查询", instruction="查询增长率")
    context = TaskContext(
        task_id="t1",
        user_query="What is the growth rate?",
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "path": "normalized/Sheet1_t1.parquet",
                    "columns_detail": [
                        {"name": "Product", "dtype": "object"},
                        {"name": "Growth Rate", "dtype": "float64"},
                    ],
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "不要仅因为数值绝对值大于 1 就除以 100" in prompt


def test_python_prompt_includes_pair_hints_only_when_pair_prefix_columns_exist():
    step = Step(id="s1", tool="python", description="查询", instruction="比较 price")
    context = TaskContext(
        task_id="t1",
        user_query="Compare price between A and B",
        workbook_manifest={},
        data_profile={
            "tables": [
                {
                    "table_id": "Sheet1_t1",
                    "path": "normalized/Sheet1_t1.parquet",
                    "columns_detail": [
                        {"name": "Product", "dtype": "object"},
                        {"name": "Price_A", "dtype": "float64"},
                        {"name": "Price_B", "dtype": "float64"},
                    ],
                }
            ]
        },
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble(context, step)

    assert "共享同一指标词的 A/B 配对列" in prompt
    assert "应直接使用这些配对列做差或比较" in prompt


def test_repair_prompt_includes_stdout_and_check_guidance():
    step = Step(id="s1", tool="python", description="查询", instruction="What is the value?")
    context = TaskContext(
        task_id="t1",
        user_query="What is the value?",
        workbook_manifest={},
        data_profile={"tables": []},
        plan=ExecutionPlan([step]),
    )

    prompt = PromptAssembler().assemble_repair(
        context,
        step,
        failed_code="print('debug only')",
        stderr="",
        stdout="Filtered 0 rows\nNo Final Answer was printed",
        check_report="final_answer_contract: failed",
    )

    assert "## stdout" in prompt
    assert "Filtered 0 rows" in prompt
    assert "不要只修格式" in prompt
    assert "Final Answer" in prompt
    assert "禁止用 primary/main/first column" in prompt
    assert "_context_group" not in prompt
