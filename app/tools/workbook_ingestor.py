"""Workbook structure scanning.

The ingestor does not modify workbooks. It produces a manifest describing
sheets and rough table candidates so preprocessing has an explicit contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries


class WorkbookIngestor:
    # 连续空行数 ≥ 此阈值时视为表间分隔
    _GAP_ROWS = 2

    def scan(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        workbook = openpyxl.load_workbook(path, read_only=False, data_only=False)
        sheets = []
        for worksheet in workbook.worksheets:
            auto_filter_ref = self._auto_filter_ref(worksheet)
            auto_filter_header = self._auto_filter_header(auto_filter_ref)
            regions = self._detect_table_regions(worksheet)
            tables = []
            for idx, bounds in enumerate(regions, start=1):
                min_row, min_col, max_row, max_col = bounds
                header_candidates = self._header_candidates(worksheet, bounds)
                notes: list[str] = []
                confidence = 0.7
                if auto_filter_header is not None and min_row <= auto_filter_header <= max_row:
                    header_candidates = self._prepend_candidate(
                        header_candidates,
                        auto_filter_header,
                    )
                    notes.append(f"AutoFilter 表头强信号: {auto_filter_ref}")
                    confidence = 0.95
                tables.append(
                    {
                        "table_id": f"{worksheet.title}_t{idx}",
                        "range": (
                            f"{get_column_letter(min_col)}{min_row}:"
                            f"{get_column_letter(max_col)}{max_row}"
                        ),
                        "header_candidates": header_candidates,
                        "confidence": confidence,
                        "notes": notes,
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
                    "auto_filter_ref": auto_filter_ref,
                    "merged_ranges": [str(item) for item in worksheet.merged_cells.ranges],
                    "tables": tables,
                }
            )
        return {
            "manifest_path": "workbook_manifest.json",
            "files": [{"path": str(path), "sheets": sheets}],
        }

    def _detect_table_regions(
        self, worksheet: Any
    ) -> list[tuple[int, int, int, int]]:
        """Split a worksheet into table regions separated by blank-row gaps.

        Returns a list of (min_row, min_col, max_row, max_col) bounding boxes.
        Adjacent non-empty rows belong to the same region; a gap of ≥ _GAP_ROWS
        consecutive blank rows starts a new region.
        """
        overall = self._non_empty_bounds(worksheet)
        if overall is None:
            return []

        min_row, min_col, max_row, max_col = overall

        # Build a set of row indices that have at least one non-empty cell
        non_empty_rows: set[int] = set()
        for row in worksheet.iter_rows(
            min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col
        ):
            for cell in row:
                if cell.value not in (None, ""):
                    non_empty_rows.add(cell.row)
                    break

        if not non_empty_rows:
            return []

        # Walk rows top-to-bottom, split into blocks separated by ≥ _GAP_ROWS blanks
        sorted_rows = sorted(non_empty_rows)
        regions: list[tuple[int, int, int, int]] = []
        block_start = sorted_rows[0]
        prev_row = sorted_rows[0]

        for row_idx in sorted_rows[1:]:
            gap = row_idx - prev_row - 1
            if gap >= self._GAP_ROWS:
                # Close current block — refine column bounds
                bounds = self._refine_col_bounds(worksheet, block_start, prev_row, min_col, max_col)
                regions.append(bounds)
                block_start = row_idx
            prev_row = row_idx

        # Close last block
        bounds = self._refine_col_bounds(worksheet, block_start, prev_row, min_col, max_col)
        regions.append(bounds)

        return regions

    def _refine_col_bounds(
        self,
        worksheet: Any,
        row_start: int,
        row_end: int,
        global_min_col: int,
        global_max_col: int,
    ) -> tuple[int, int, int, int]:
        """Tighten column bounds to the actual non-empty range within a row block."""
        actual_min_col = global_max_col
        actual_max_col = global_min_col
        for row in worksheet.iter_rows(
            min_row=row_start,
            max_row=row_end,
            min_col=global_min_col,
            max_col=global_max_col,
        ):
            for cell in row:
                if cell.value not in (None, ""):
                    actual_min_col = min(actual_min_col, cell.column)
                    actual_max_col = max(actual_max_col, cell.column)
        return (row_start, actual_min_col, row_end, actual_max_col)

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

    def _auto_filter_ref(self, worksheet: Any) -> str | None:
        value = getattr(getattr(worksheet, "auto_filter", None), "ref", None)
        return str(value) if value else None

    def _auto_filter_header(self, auto_filter_ref: str | None) -> int | None:
        if not auto_filter_ref:
            return None
        try:
            _, min_row, _, _ = range_boundaries(auto_filter_ref)
        except ValueError:
            return None
        return min_row

    def _prepend_candidate(self, candidates: list[int], candidate: int) -> list[int]:
        return [candidate, *[item for item in candidates if item != candidate]][:3]

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
