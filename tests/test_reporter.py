"""Reporter tests — uses a fake LLM so no network calls are needed."""

import asyncio
from collections import OrderedDict
from types import SimpleNamespace

from app.agent.plan import ExecutionPlan, Step
from app.agent.reporter import Reporter
from app.context.task_context import TaskContext
from app.tools.result_checker import CheckResult, CheckItem


class FakeLLM:
    """Returns a canned response that echoes the chapter title."""

    def __init__(self):
        self.calls: list[str] = []

    async def call(
        self,
        prompt: str,
        max_tokens: int = 2000,
        reasoning_callback=None,
    ) -> str:
        self.calls.append(prompt)
        # Extract chapter title from prompt to make assertions possible
        if "第1章" in prompt:
            return "本章分析了整体采购趋势。平均采购金额为 **52.3 万元**，同比增长 12%。"
        if "第2章" in prompt:
            return "深入分析发现，IT 类采购占比最高（38%），其次是办公用品（25%）。"
        if "第3章" in prompt:
            return "综合来看，采购效率有待提升。建议优化审批流程，预计可缩短 15% 时长。"
        return "报告章节内容。"


class FakeStreamingLLM(FakeLLM):
    async def stream(self, prompt: str, max_tokens: int = 2000, reasoning_callback=None):
        self.calls.append(prompt)
        for token in ("流式", "章节", "内容"):
            yield token


class FakeWorkspace:
    def list_output_files(self):
        return ["output/采购分析.xlsx", "output/趋势图.png"]


def _make_context(with_outline: bool = True) -> TaskContext:
    outline = []
    if with_outline:
        outline = [
            {"title": "采购总览", "related_steps": ["s1"], "word_count": 500},
            {"title": "分类分析", "related_steps": ["s2"], "word_count": 800},
            {"title": "结论与建议", "related_steps": ["s1", "s2"], "word_count": 600},
        ]

    plan = ExecutionPlan(
        steps=[
            Step(id="s1", tool="python", description="统计", instruction="统计", status="done"),
            Step(id="s2", tool="python", description="分类", instruction="分类", status="done"),
        ],
        report_outline=outline,
    )

    ctx = TaskContext(
        task_id="t1",
        user_query="分析采购数据，按类别统计并给出建议",
        workbook_manifest={},
        data_profile={},
        plan=plan,
    )
    ctx.step_summaries = OrderedDict([
        ("s1", "统计: 总计 500 条采购记录，平均金额 52.3 万元"),
        ("s2", "分类: IT 类 38%，办公用品 25%，其他 37%"),
    ])
    ctx.key_findings = ["IT 类采购金额同比增长 12%", "办公用品采购周期偏长"]
    ctx.artifact_manifest = [
        {"path": "output/趋势图.png", "kind": "chart", "description": "采购趋势图"},
    ]
    ctx.quality_checks = [
        CheckResult(step_id="s1", status="passed", checks=[]),
        CheckResult(
            step_id="s2",
            status="passed",
            checks=[CheckItem("stdout_not_empty", "warning", "部分类别数据量不足")],
            warnings=["部分类别数据量不足"],
        ),
    ]
    return ctx


# ── Tests ──


def test_generate_multi_section_report():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()

    report = asyncio.run(reporter.generate(ctx, workspace))

    # 3 LLM calls, one per chapter
    assert len(llm.calls) == 3

    # Report structure
    assert "# 分析报告" in report
    assert "## 目录" in report
    assert "1. 采购总览" in report
    assert "2. 分类分析" in report
    assert "3. 结论与建议" in report

    # Chapter content is included
    assert "52.3 万元" in report
    assert "IT 类采购占比最高" in report
    assert "优化审批流程" in report

    # Chart references
    assert "![采购趋势图]" in report
    assert "output/趋势图.png" in report

    # Attachments
    assert "## 附件" in report
    assert "采购分析.xlsx" in report


def test_generate_streams_report_sections():
    llm = FakeStreamingLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()
    streamed: list[str] = []

    async def on_token(token: str):
        streamed.append(token)

    report = asyncio.run(reporter.generate(ctx, workspace, stream_callback=on_token))

    assert len(llm.calls) == 3
    assert "# 分析报告" in "".join(streamed)
    assert "## 1. 采购总览" in "".join(streamed)
    assert "流式章节内容" in "".join(streamed)
    assert "流式章节内容" in report
    assert "## 附件" in report


def test_chapter_receives_prev_ending():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()

    asyncio.run(reporter.generate(ctx, workspace))

    # First chapter prompt should NOT have "上一章结尾"
    assert "上一章结尾" not in llm.calls[0]

    # Second chapter prompt SHOULD have "上一章结尾"
    assert "上一章结尾" in llm.calls[1]


def test_chapter_prompt_includes_relevant_data():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()

    asyncio.run(reporter.generate(ctx, workspace))

    # Chapter 1 is related to s1 — should include s1 summary
    assert "统计: 总计 500 条" in llm.calls[0]
    # Chapter 2 is related to s2
    assert "分类: IT 类 38%" in llm.calls[1]
    # Chapter 3 is related to both s1 and s2
    assert "统计" in llm.calls[2]
    assert "分类" in llm.calls[2]


def test_chapter_prompt_includes_warnings():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()

    asyncio.run(reporter.generate(ctx, workspace))

    # Chapter 2 (分类分析, related to s2) should include the s2 warning
    assert "部分类别数据量不足" in llm.calls[1]


def test_chapter_prompt_includes_outline_and_user_query():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    workspace = FakeWorkspace()

    asyncio.run(reporter.generate(ctx, workspace))

    for call in llm.calls:
        assert "分析采购数据" in call      # user query
        assert "采购总览" in call           # outline present
        assert "分类分析" in call
        assert "结论与建议" in call


def test_simple_response_without_outline():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=False)
    workspace = FakeWorkspace()

    report = asyncio.run(reporter.generate(ctx, workspace))

    # No LLM calls — simple assembly
    assert len(llm.calls) == 0
    assert "# 分析结果" in report
    assert "统计: 总计 500 条" in report
    assert "分类: IT 类 38%" in report
    assert "## 附件" in report
    assert "采购分析.xlsx" in report


def test_simple_response_preserves_final_answer_section():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=False)
    ctx.final_answers["s1"] = "14400"
    ctx.step_summaries["s1"] = "统计: debug output\nFinal Answer: 14400"
    workspace = FakeWorkspace()

    report = asyncio.run(reporter.generate(ctx, workspace))

    assert "## 最终答案" in report
    assert "Final Answer: 14400" in report
    assert report.index("## 最终答案") < report.index("## 简要结论")


def test_full_report_preserves_final_answer_section():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=True)
    ctx.final_answers["s1"] = "52.3"
    workspace = FakeWorkspace()

    report = asyncio.run(reporter.generate(ctx, workspace))

    assert "## 最终答案" in report
    assert "Final Answer: 52.3" in report
    assert report.index("## 最终答案") < report.index("## 1. 采购总览")


def test_key_findings_in_simple_response():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    ctx = _make_context(with_outline=False)
    workspace = FakeWorkspace()

    report = asyncio.run(reporter.generate(ctx, workspace))

    assert "IT 类采购金额同比增长 12%" in report
    assert "办公用品采购周期偏长" in report


def test_system_prompt_loaded():
    llm = FakeLLM()
    reporter = Reporter(llm_client=llm)
    # Should load from file
    assert "行文专业" in reporter._system_prompt
    assert "条理清晰" in reporter._system_prompt
