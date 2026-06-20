import openpyxl

from app.main import _mime_for_path, _report_for_ui, _table_preview_for_path


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
