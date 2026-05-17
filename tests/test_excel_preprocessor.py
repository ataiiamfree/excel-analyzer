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


def test_manifest_path_fallback():
    manifest = {"path": "old_path.json"}
    assert ExcelPreprocessor().normalize_manifest_path(manifest) == "old_path.json"


def test_manifest_path_none():
    assert ExcelPreprocessor().normalize_manifest_path({}) is None


def test_dedupe_headers():
    preprocessor = ExcelPreprocessor()
    headers = preprocessor._dedupe_headers(["名称", "金额", "金额", None, "金额"])
    assert headers == ["名称", "金额", "金额_2", "列4", "金额_3"]


def test_merge_multi_level_headers():
    preprocessor = ExcelPreprocessor()
    rows = [
        ["采购金额", "采购金额", "销售金额", "销售金额"],
        ["计划", "实际", "计划", "实际"],
        [100, 110, 200, 190],
    ]
    preprocessor._merge_multi_level_headers(rows, header_row=2)
    assert rows[1] == ["采购金额_计划", "采购金额_实际", "销售金额_计划", "销售金额_实际"]


def test_merge_multi_level_headers_dedup():
    """合并单元格填充后上下层相同时应去重。"""
    preprocessor = ExcelPreprocessor()
    rows = [
        ["总额", "总额"],
        ["总额", "总额"],  # 与上面完全相同（合并填充后的结果）
        [100, 200],
    ]
    preprocessor._merge_multi_level_headers(rows, header_row=2)
    assert rows[1] == ["总额", "总额"]  # 不会变成 "总额_总额"


def test_detect_data_end_with_footnote():
    preprocessor = ExcelPreprocessor()
    rows = [
        ["名称", "金额"],
        ["A", 100],
        ["B", 200],
        ["备注：仅供参考", None],
        [None, None],
    ]
    end = preprocessor._detect_data_end(rows, header_row=1)
    assert end == 3  # 第3行（B, 200）是最后的有效数据行


def test_detect_data_end_no_footnote():
    preprocessor = ExcelPreprocessor()
    rows = [
        ["名称", "金额"],
        ["A", 100],
        ["B", 200],
    ]
    end = preprocessor._detect_data_end(rows, header_row=1)
    assert end == 3


def test_classify_rows_blank_and_title():
    preprocessor = ExcelPreprocessor()
    rows = [
        ["采购报表 2024年", None],  # title (before header)
        [None, None],               # also title (before header, even though blank)
        ["名称", "金额"],           # header (row 3)
        [None, None],               # blank (after header)
        ["A", 100],
    ]
    flags = preprocessor.classify_rows(rows, header_row=3, data_end=5)
    assert flags[1]["kind"] == "title"
    assert flags[1]["exclude"] is True
    assert flags[2]["kind"] == "title"   # before header → title
    assert flags[2]["exclude"] is True
    assert flags[4]["kind"] == "blank"   # after header, empty → blank
    assert flags[4]["exclude"] is True
    assert flags[5]["kind"] == "data"
    assert flags[5]["exclude"] is False
