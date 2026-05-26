from app.main import _mime_for_path, _report_for_ui


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
