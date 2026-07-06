import pandas as pd

from app.tools.excel_preprocessor import NormalizedTable
from app.tools.profiler import Profiler


def test_profiler_detects_deduped_repeated_header_families(tmp_path):
    path = tmp_path / "normalized.xlsx"
    pd.DataFrame(
        {
            "weightlifter": ["a", "b"],
            "press": [100, 110],
            "press_2": [105, 115],
            "press_3": [110, 120],
            "_source_file": ["book.xlsx", "book.xlsx"],
            "_source_sheet": ["Sheet1", "Sheet1"],
            "_source_row": [2, 3],
        }
    ).to_excel(path, index=False)
    table = NormalizedTable(
        table_id="Sheet1_t1",
        source_file="book.xlsx",
        source_sheet="Sheet1",
        source_range="A1:D3",
        parquet_path=str(path),
        preview_xlsx_path=str(path),
        columns=[],
        row_count=2,
    )

    profile = Profiler().profile([table])

    families = profile["tables"][0]["column_families"]
    assert families == [
        {
            "base": "press",
            "kind": "deduped_repeated_header",
            "columns": ["press", "press_2", "press_3"],
            "count": 3,
            "dtype": "int64",
        }
    ]


def test_profiler_exposes_header_path_and_keeps_multi_level_columns_ungrouped(tmp_path):
    path = tmp_path / "region_year.xlsx"
    pd.DataFrame(
        {
            "Species": ["Cod", "Haddock"],
            "2022": [100, 80],
            "2023": [110, 90],
            "2022_2": [50, 40],
            "2023_2": [55, 45],
            "_source_file": ["book.xlsx"] * 2,
            "_source_sheet": ["Sheet1"] * 2,
            "_source_row": [4, 5],
        }
    ).to_excel(path, index=False)

    table = NormalizedTable(
        table_id="Sheet1_t1",
        source_file="book.xlsx",
        source_sheet="Sheet1",
        source_range="A1:E5",
        parquet_path=str(path),
        preview_xlsx_path=str(path),
        columns=[],
        row_count=2,
        header_paths={
            "Species": ["Species"],
            "2022": ["Landings into", "Scotland", "2022"],
            "2023": ["Landings into", "Scotland", "2023"],
            "2022_2": ["Landings into", "England", "2022"],
            "2023_2": ["Landings into", "England", "2023"],
        },
    )

    profile = Profiler().profile([table])["tables"][0]
    detail_by_name = {item["name"]: item for item in profile["columns_detail"]}

    # Multi-level columns are individually preserved (not collapsed by the
    # {N}-pattern grouper) so their lineage stays visible to the model.
    assert set(detail_by_name) == {"Species", "2022", "2023", "2022_2", "2023_2"}
    assert detail_by_name["2023_2"]["header_path"] == [
        "Landings into",
        "England",
        "2023",
    ]
    assert detail_by_name["Species"]["header_path"] == ["Species"]
    assert profile["columns_grouped"] == []
