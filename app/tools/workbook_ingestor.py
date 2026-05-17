"""Workbook structure scanning.

The ingestor does not modify workbooks. It produces a manifest describing
sheets and rough table candidates so preprocessing has an explicit contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter


class WorkbookIngestor:
    def scan(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        workbook = openpyxl.load_workbook(path, read_only=False, data_only=False)
        sheets = []
        for worksheet in workbook.worksheets:
            bounds = self._non_empty_bounds(worksheet)
            tables = []
            if bounds is not None:
                min_row, min_col, max_row, max_col = bounds
                tables.append(
                    {
                        "table_id": f"{worksheet.title}_t1",
                        "range": (
                            f"{get_column_letter(min_col)}{min_row}:"
                            f"{get_column_letter(max_col)}{max_row}"
                        ),
                        "header_candidates": self._header_candidates(worksheet, bounds),
                        "confidence": 0.7,
                        "notes": [],
                    }
                )
            sheets.append(
                {
                    "name": worksheet.title,
                    "max_row": worksheet.max_row,
                    "max_col": worksheet.max_column,
                    "hidden_rows": [
                        idx
                        for idx, dim in worksheet.row_dimensions.items()
                        if getattr(dim, "hidden", False)
                    ],
                    "hidden_cols": [
                        key
                        for key, dim in worksheet.column_dimensions.items()
                        if getattr(dim, "hidden", False)
                    ],
                    "merged_ranges": [str(item) for item in worksheet.merged_cells.ranges],
                    "tables": tables,
                }
            )
        return {
            "manifest_path": "workbook_manifest.json",
            "files": [{"path": str(path), "sheets": sheets}],
        }

    def _non_empty_bounds(self, worksheet: Any) -> tuple[int, int, int, int] | None:
        min_row = min_col = None
        max_row = max_col = 0
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.value in (None, ""):
                    continue
                min_row = cell.row if min_row is None else min(min_row, cell.row)
                min_col = cell.column if min_col is None else min(min_col, cell.column)
                max_row = max(max_row, cell.row)
                max_col = max(max_col, cell.column)
        if min_row is None or min_col is None:
            return None
        return min_row, min_col, max_row, max_col

    def _header_candidates(
        self, worksheet: Any, bounds: tuple[int, int, int, int]
    ) -> list[int]:
        min_row, min_col, max_row, max_col = bounds
        candidates = []
        scan_end = min(max_row, min_row + 19)
        width = max_col - min_col + 1
        for row_idx in range(min_row, scan_end + 1):
            values = [
                worksheet.cell(row_idx, col_idx).value
                for col_idx in range(min_col, max_col + 1)
            ]
            non_empty = [value for value in values if value not in (None, "")]
            if not non_empty:
                continue
            text_count = sum(isinstance(value, str) for value in non_empty)
            if len(non_empty) / width >= 0.4 and text_count / len(non_empty) >= 0.6:
                candidates.append(row_idx)
        return candidates[:3] or [min_row]
