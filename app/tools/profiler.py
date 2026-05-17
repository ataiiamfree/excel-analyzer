"""Data profiling for normalized tables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.tools.excel_preprocessor import NormalizedTable


class Profiler:
    def profile(self, tables: list[NormalizedTable]) -> dict[str, Any]:
        return {"tables": [self._profile_table(table) for table in tables]}

    def _profile_table(self, table: NormalizedTable) -> dict[str, Any]:
        df = self._read_table(table)
        visible_columns = [col for col in df.columns if not str(col).startswith("_source_")]
        columns_info = [self._profile_column(df, col) for col in visible_columns]
        grouped, detail = self._group_similar_columns(columns_info)
        sample = df[visible_columns].head(3).to_dict(orient="records")
        return {
            "table_id": table.table_id,
            "source": f"{table.source_sheet}!{table.source_range}",
            "path": table.parquet_path,
            "shape": {"rows": len(df), "cols": len(visible_columns)},
            "columns_grouped": grouped,
            "columns_detail": detail,
            "sample_rows": sample,
            "warnings": table.warnings,
        }

    def _read_table(self, table: NormalizedTable) -> pd.DataFrame:
        path = Path(table.parquet_path)
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_excel(path)

    def _profile_column(self, df: pd.DataFrame, col: str) -> dict[str, Any]:
        series = df[col]
        info: dict[str, Any] = {
            "name": col,
            "dtype": str(series.dtype),
            "null_pct": round(float(series.isna().mean()), 3),
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
        return info

    def _group_similar_columns(
        self, columns: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        ungrouped = []
        for col in columns:
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
