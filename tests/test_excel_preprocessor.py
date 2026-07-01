from pathlib import Path

import openpyxl
import pandas as pd

from app.tools.excel_preprocessor import ExcelPreprocessor
from app.tools.profiler import Profiler


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


def test_formula_without_cached_value_warns(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    workbook_path = raw_dir / "formula.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["A", "B", "Total"])
    ws.append([1, 2, "=A2+B2"])
    workbook.save(workbook_path)

    manifest = {
        "manifest_path": "workbook_manifest.json",
        "files": [
            {
                "path": str(workbook_path),
                "sheets": [
                    {
                        "name": "Sheet1",
                        "tables": [
                            {
                                "table_id": "Sheet1_t1",
                                "range": "A1:C2",
                                "header_candidates": [1],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = ExcelPreprocessor().process(workbook_path, manifest)

    assert result.tables[0].row_count == 1
    assert any("公式没有缓存计算值" in warning for warning in result.tables[0].warnings)


def test_process_writes_to_explicit_output_dir(tmp_path):
    workbook_path = tmp_path / "input.xlsx"
    output_dir = tmp_path / "custom_normalized"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["名称", "金额"])
    ws.append(["A", 10])
    workbook.save(workbook_path)

    manifest = {
        "manifest_path": "workbook_manifest.json",
        "files": [
            {
                "path": str(workbook_path),
                "sheets": [
                    {
                        "name": "Sheet1",
                        "tables": [
                            {
                                "table_id": "Sheet1_t1",
                                "range": "A1:B2",
                                "header_candidates": [1],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = ExcelPreprocessor().process(workbook_path, manifest, output_dir=output_dir)

    assert result.tables[0].row_count == 1
    assert output_dir in Path(result.tables[0].parquet_path).parents


def test_process_reuses_previous_headers_for_headerless_continuation_block(tmp_path):
    workbook_path = tmp_path / "continuation.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["Division", "Subdivision", "Serial No."])
    ws.append(["Foundation", "Earthwork", 1])
    ws.append([None, None, 2])
    ws.append([None, None, None])
    ws.append([None, None, None])
    ws.append([None, None, None])
    ws.append(["Decoration", "Floor", 1])
    ws.append([None, None, 2])
    ws.append([None, "Doors", 1])
    workbook.save(workbook_path)

    manifest = {
        "manifest_path": "workbook_manifest.json",
        "files": [
            {
                "path": str(workbook_path),
                "sheets": [
                    {
                        "name": "Sheet1",
                        "tables": [
                            {
                                "table_id": "Sheet1_t1",
                                "range": "A1:C3",
                                "header_candidates": [1],
                            },
                            {
                                "table_id": "Sheet1_t2",
                                "range": "A7:C9",
                                # Simulates a later text-heavy row being
                                # mistaken for a header candidate.
                                "header_candidates": [9],
                            },
                        ],
                    }
                ],
            }
        ],
    }

    result = ExcelPreprocessor().process(workbook_path, manifest)
    second = result.tables[1]
    path = Path(second.parquet_path)
    dataframe = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_excel(path)

    assert list(dataframe.columns[:3]) == ["Division", "Subdivision", "Serial No."]
    assert dataframe.loc[0, "Division"] == "Decoration"
    assert dataframe.loc[0, "Serial No."] == 1
    assert any("续表" in warning for warning in second.warnings)


def test_process_converts_group_title_rows_to_context_column(tmp_path):
    workbook_path = tmp_path / "grouped.xlsx"
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["Serial No.", "Project Name", "Unit", "Quantity", "Remarks"])
    ws.append(["First Floor", None, None, None, None])
    ws.merge_cells("A2:D2")
    ws.append([1, "Floor Tiles (1000×1000)", "㎡", 72.4, "ok"])
    ws.append([2, "Kitchen Wall Tiles", "㎡", 60, "ok"])
    ws.append(["Second Floor", None, None, None, "XXXXX"])
    ws.append([1, "Floor Tiles (1000×1000)", "㎡", 120, "ok"])
    workbook.save(workbook_path)

    manifest = {
        "manifest_path": "workbook_manifest.json",
        "files": [
            {
                "path": str(workbook_path),
                "sheets": [
                    {
                        "name": "Sheet1",
                        "tables": [
                            {
                                "table_id": "Sheet1_t1",
                                "range": "A1:E6",
                                "header_candidates": [1],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = ExcelPreprocessor().process(workbook_path, manifest)
    table = result.tables[0]
    path = Path(table.parquet_path)
    dataframe = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_excel(path)

    assert table.row_count == 3
    assert "_context_group" in dataframe.columns
    assert dataframe["Project Name"].tolist() == [
        "Floor Tiles (1000×1000)",
        "Kitchen Wall Tiles",
        "Floor Tiles (1000×1000)",
    ]
    assert dataframe["_context_group"].tolist() == [
        "First Floor",
        "First Floor",
        "Second Floor",
    ]
    assert table.enum_columns["_context_group"] == ["First Floor", "Second Floor"]
    assert any("_context_group" in warning for warning in table.warnings)


def test_process_records_enum_and_oversized_metadata_without_truncating_data(tmp_path):
    workbook_path = tmp_path / "input.xlsx"
    long_text = "很长的说明" * 50
    workbook = openpyxl.Workbook()
    ws = workbook.active
    ws.title = "Sheet1"
    ws.append(["状态", "说明"])
    ws.append(["已完成", long_text])
    ws.append(["未开始", "短说明"])
    ws.append(["已完成", "短说明2"])
    ws.append(["已完成", "短说明3"])
    ws.append(["已完成", "短说明4"])
    workbook.save(workbook_path)

    manifest = {
        "manifest_path": "workbook_manifest.json",
        "files": [
            {
                "path": str(workbook_path),
                "sheets": [
                    {
                        "name": "Sheet1",
                        "tables": [
                            {
                                "table_id": "Sheet1_t1",
                                "range": "A1:B6",
                                "header_candidates": [1],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    result = ExcelPreprocessor().process(workbook_path, manifest)
    table = result.tables[0]

    assert table.enum_columns == {"状态": ["已完成", "未开始"]}
    assert table.oversized_cells[0]["column"] == "说明"
    assert table.oversized_cells[0]["source_row"] == 2

    path = Path(table.parquet_path)
    dataframe = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_excel(path)
    assert dataframe.loc[0, "说明"] == long_text

    profile = Profiler().profile(result.tables)
    sample_value = profile["tables"][0]["sample_rows"][0]["说明"]
    assert "[TRUNCATED:" in sample_value
