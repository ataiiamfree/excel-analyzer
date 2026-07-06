"""Data profiling for normalized tables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.tools.excel_preprocessor import NormalizedTable


class Profiler:
    sample_cell_max_chars = 200
    enum_max_unique_values = 15
    enum_max_unique_ratio = 0.5

    def profile(self, tables: list[NormalizedTable]) -> dict[str, Any]:
        return {"tables": [self._profile_table(table) for table in tables]}

    def _profile_table(self, table: NormalizedTable) -> dict[str, Any]:
        df = self._read_table(table)
        visible_columns = [col for col in df.columns if not str(col).startswith("_source_")]
        columns_info = [
            self._profile_column(df, col, table.header_paths) for col in visible_columns
        ]
        grouped, detail = self._group_similar_columns(columns_info)
        column_families = self._detect_column_families(columns_info)
        sample = self._sample_rows(df, visible_columns)
        return {
            "table_id": table.table_id,
            "source": f"{table.source_sheet}!{table.source_range}",
            "path": table.parquet_path,
            "shape": {"rows": len(df), "cols": len(visible_columns)},
            "columns_grouped": grouped,
            "column_families": column_families,
            "columns_detail": detail,
            "enum_columns": table.enum_columns,
            "oversized_cells": table.oversized_cells,
            "sample_rows": sample,
            "warnings": table.warnings,
        }

    def _read_table(self, table: NormalizedTable) -> pd.DataFrame:
        path = Path(table.parquet_path)
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_excel(path)

    def _profile_column(
        self,
        df: pd.DataFrame,
        col: str,
        header_paths: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        series = df[col]
        path = (header_paths or {}).get(col) or [col]
        info: dict[str, Any] = {
            "name": col,
            "dtype": str(series.dtype),
            "null_pct": round(float(series.isna().mean()), 3),
            "header_path": list(path),
        }
        if pd.api.types.is_numeric_dtype(series):
            non_null = series.dropna()
            if not non_null.empty:
                info.update(
                    {
                        "min": float(non_null.min()),
                        "max": float(non_null.max()),
                        "mean": round(float(non_null.mean()), 2),
                        "p95": round(float(non_null.quantile(0.95)), 2),
                    }
                )
        elif pd.api.types.is_datetime64_any_dtype(series):
            non_null = series.dropna()
            if not non_null.empty:
                info["range"] = [str(non_null.min())[:10], str(non_null.max())[:10]]
        else:
            non_null = series.dropna().astype(str)
            info["nunique"] = int(non_null.nunique())
            info["sample"] = non_null.unique()[:3].tolist()
            enum_values = self._enum_values(non_null)
            if enum_values:
                info["enum_values"] = enum_values
        return info

    def _sample_rows(
        self,
        df: pd.DataFrame,
        visible_columns: list[str],
    ) -> list[dict[str, Any]]:
        rows = []
        for record in df[visible_columns].head(3).to_dict(orient="records"):
            rows.append(
                {
                    key: self._truncate_sample_value(value)
                    for key, value in record.items()
                }
            )
        return rows

    def _truncate_sample_value(self, value: Any) -> Any:
        if not isinstance(value, str) or len(value) <= self.sample_cell_max_chars:
            return value
        return (
            value[: self.sample_cell_max_chars]
            + f"[TRUNCATED:原长度{len(value)},请勿基于此单元格完整内容做分析]"
        )

    def _enum_values(self, series: pd.Series) -> list[str]:
        values = series.astype(str).str.strip()
        values = values[values != ""]
        if values.empty:
            return []
        unique_values = sorted(values.unique().tolist())
        unique_ratio = len(unique_values) / len(values)
        if (
            len(unique_values) <= self.enum_max_unique_values
            and unique_ratio < self.enum_max_unique_ratio
        ):
            return unique_values
        return []

    def _detect_column_families(
        self,
        columns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect repeated logical columns created by duplicate Excel headers.

        pandas/openpyxl-style header de-duplication often turns repeated header
        cells into `name`, `name_2`, `name_3`. These are usually not unrelated
        fields; they are sibling observations under the same visual header
        (attempts, periods, regions, material variants, etc.). Exposing this as
        metadata lets the code-generation step inspect the whole family instead
        of accidentally taking the first column.
        """

        by_name = {str(col.get("name")): col for col in columns if col.get("name")}
        families: list[dict[str, Any]] = []
        consumed: set[str] = set()

        for name in by_name:
            if name in consumed or self._dedupe_suffix(name) is not None:
                continue
            siblings = [name]
            index = 2
            while f"{name}_{index}" in by_name:
                siblings.append(f"{name}_{index}")
                index += 1
            if len(siblings) < 2:
                continue

            consumed.update(siblings)
            dtype_counts: dict[str, int] = {}
            for sibling in siblings:
                dtype = str(by_name[sibling].get("dtype", "?"))
                dtype_counts[dtype] = dtype_counts.get(dtype, 0) + 1
            dominant_dtype = max(dtype_counts, key=dtype_counts.get)
            families.append(
                {
                    "base": name,
                    "kind": "deduped_repeated_header",
                    "columns": siblings,
                    "count": len(siblings),
                    "dtype": dominant_dtype,
                }
            )
        return families

    def _dedupe_suffix(self, name: str) -> int | None:
        match = re.match(r"^.+_([2-9]\d*)$", name)
        if not match:
            return None
        return int(match.group(1))

    def _group_similar_columns(
        self, columns: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        ungrouped = []
        for col in columns:
            path = col.get("header_path") or []
            # Columns with multi-level lineage carry meaningful group/parent
            # info; collapsing them into a `pattern(4列)` summary throws that
            # away. Keep them individually so the lineage stays visible.
            if isinstance(path, list) and len(path) > 1:
                ungrouped.append(col)
                continue
            pattern = re.sub(r"\d+", "{N}", col["name"])
            if pattern != col["name"]:
                groups.setdefault(pattern, []).append(col)
            else:
                ungrouped.append(col)

        grouped = []
        for pattern, cols in groups.items():
            if len(cols) < 3:
                ungrouped.extend(cols)
                continue
            nums = [
                int(match.group())
                for item in cols
                if (match := re.search(r"\d+", item["name"]))
            ]
            label = pattern
            if nums:
                label = pattern.replace("{N}", f"[{min(nums)}-{max(nums)}]")
            grouped.append({"pattern": label, "count": len(cols), "dtype": cols[0]["dtype"]})
        return grouped, ungrouped
