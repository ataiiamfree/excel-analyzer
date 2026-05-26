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
    assert table["header_candidates"] == [2]
    assert table["confidence"] == 0.95
    assert any("AutoFilter" in note for note in table["notes"])


def test_autofilter_header_does_not_absorb_text_heavy_data_rows(tmp_path):
    workbook_path = tmp_path / "autofilter_text_rows.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "过超去重"
    ws.append(["用户编号", "用户名称", "供电单位", "计量点编号", "类型"])
    ws.append(["0950000075750333", "陈斌", "龙华供电局", "300127910614703843", "过"])
    ws.append(["0947000065600055", "深圳市同乐股份合作公司新布分公司", "龙城供电分局", "300176473213656014", "过"])
    ws.auto_filter.ref = "A1:E3"
    workbook.save(workbook_path)

    manifest = WorkbookIngestor().scan(workbook_path)
    table = manifest["files"][0]["sheets"][0]["tables"][0]

    assert table["header_candidates"] == [1]
