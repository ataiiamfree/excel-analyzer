from app.tools.excel_preprocessor import ExcelPreprocessor


def test_summary_keyword_inside_business_value_is_not_auto_excluded():
    rows = [
        ["类型", "金额"],
        ["合计包采购", 10],
        ["普通采购", 20],
        ["其他采购", 30],
        ["合计", 60],
    ]

    flags = ExcelPreprocessor().classify_rows(rows, header_row=1, data_end=5)

    assert flags[2]["exclude"] is False
    assert flags[2]["kind"] == "possible_summary"
    assert flags[5]["exclude"] is True
    assert flags[5]["kind"] == "summary"


def test_manifest_path_accepts_new_schema_name():
    manifest = {"manifest_path": "workbook_manifest.json", "files": []}

    assert ExcelPreprocessor().normalize_manifest_path(manifest) == "workbook_manifest.json"
