import openpyxl

from app.agent.plan import Step
from app.agent.types import StepResult
from app.main import (
    _format_plan_for_ui,
    _format_step_result_for_ui,
    _message_ui_content,
    _message_ui_marker,
    _message_ui_metadata,
    _mime_for_path,
    _report_for_ui,
    _table_preview_for_path,
)


def test_report_for_ui_removes_attachment_links():
    report = "# 分析结果\n\n正文\n\n## 附件\n- [output/result.xlsx](output/result.xlsx)\n"

    assert _report_for_ui(report) == "# 分析结果\n\n正文"


def test_mime_for_xlsx_is_explicit():
    assert (
        _mime_for_path("/tmp/result.xlsx")
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_mime_for_unknown_file_falls_back():
    assert _mime_for_path("/tmp/result.unknown") == "application/octet-stream"


def test_table_preview_reads_csv(tmp_path):
    output = tmp_path / "result.csv"
    output.write_text("门店,销售额\n杭州西湖店,753.3\n上海南京路店,664.9\n", encoding="utf-8")

    preview = _table_preview_for_path(str(output))

    assert preview is not None
    assert list(preview.columns) == ["门店", "销售额"]
    assert preview.iloc[0]["门店"] == "杭州西湖店"


def test_table_preview_reads_first_excel_sheet(tmp_path):
    output = tmp_path / "result.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.append(["部门", "执行率"])
    ws.append(["销售部", 108.26])
    workbook.save(output)

    preview = _table_preview_for_path(str(output))

    assert preview is not None
    assert list(preview.columns) == ["部门", "执行率"]
    assert preview.iloc[0]["部门"] == "销售部"


def test_format_plan_for_ui_lists_execute_steps():
    steps = [
        Step(id="s1", tool="python", description="读取并分析", instruction="读取数据"),
        Step(id="s2", tool="python", description="导出结果", instruction="保存表格"),
    ]

    text = _format_plan_for_ui(steps)

    assert "**执行计划**" in text
    assert "`python` 读取并分析" in text
    assert "2. `python` 导出结果" in text


def test_format_step_result_for_ui_includes_stdout_files_and_script():
    step = Step(id="s1", tool="python", description="统计", instruction="统计")
    result = StepResult(
        stdout="总计 100 行",
        files=["output/result.csv"],
        script_path="scripts/s1_attempt_0.py",
    )

    text = _format_step_result_for_ui(step, result)

    assert "状态：完成" in text
    assert "总计 100 行" in text
    assert "output/result.csv" in text
    assert "scripts/s1_attempt_0.py" in text


def test_message_ui_metadata_marks_visual_kind():
    assert _message_ui_metadata("reasoning") == {"cx_kind": "reasoning"}


def test_message_ui_content_embeds_hidden_kind_marker():
    content = _message_ui_content("reasoning", "过程")

    assert "<span" not in content
    assert "data-cx-kind" not in content
    assert content.startswith(_message_ui_marker("reasoning"))
    assert content.endswith("\n过程")
