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
