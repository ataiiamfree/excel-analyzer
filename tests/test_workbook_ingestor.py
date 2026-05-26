import openpyxl

from app.tools.workbook_ingestor import WorkbookIngestor


def test_scan_uses_autofilter_as_strong_header_signal(tmp_path):
    workbook_path = tmp_path / "autofilter.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "采购"
    ws.append(["2026 年采购台账", None, None])
    ws.append(["类别", "金额", "状态"])
    ws.append(["工程", 100, "已完成"])
    ws.append(["服务", 200, "未开始"])
    ws.auto_filter.ref = "A2:C4"
    workbook.save(workbook_path)

    manifest = WorkbookIngestor().scan(workbook_path)
    sheet = manifest["files"][0]["sheets"][0]
    table = sheet["tables"][0]

    assert sheet["auto_filter_ref"] == "A2:C4"
    assert table["header_candidates"][0] == 2
    assert table["confidence"] == 0.95
    assert any("AutoFilter" in note for note in table["notes"])
