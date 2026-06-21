"""Shared UI helper functions for legacy tests and API artifact previews."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import pandas as pd

from app.agent.plan import Step
from app.agent.types import StepResult


TABLE_PREVIEW_ROWS = 50
TABLE_PREVIEW_COLS = 24
TABLE_PREVIEW_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
UI_MARKER_PREFIX = "\u2063\u2062"
UI_MARKER_SUFFIX = "\u2062\u2063"
UI_KIND_MARKERS = {
    "reasoning": f"{UI_MARKER_PREFIX}\u200b{UI_MARKER_SUFFIX}",
    "progress": f"{UI_MARKER_PREFIX}\u200c{UI_MARKER_SUFFIX}",
    "plan": f"{UI_MARKER_PREFIX}\u200d{UI_MARKER_SUFFIX}",
    "execute": f"{UI_MARKER_PREFIX}\u2060{UI_MARKER_SUFFIX}",
    "result": f"{UI_MARKER_PREFIX}\u2061{UI_MARKER_SUFFIX}",
    "artifact": f"{UI_MARKER_PREFIX}\u2063{UI_MARKER_SUFFIX}",
    "preview": f"{UI_MARKER_PREFIX}\u2064{UI_MARKER_SUFFIX}",
}


def _report_for_ui(report: str) -> str:
    """Remove relative artifact links that are sent separately as elements."""
    marker = "\n## 附件"
    if marker in report:
        return report.split(marker, 1)[0].rstrip()
    if report.startswith("## 附件"):
        return ""
    return report


def _mime_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _table_preview_for_path(path: str) -> pd.DataFrame | None:
    """Load a bounded table preview for inline rendering."""
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(p, encoding="utf-8-sig", nrows=TABLE_PREVIEW_ROWS)
        elif suffix == ".tsv":
            df = pd.read_csv(p, sep="\t", encoding="utf-8-sig", nrows=TABLE_PREVIEW_ROWS)
        elif suffix in {".xlsx", ".xlsm", ".xls"}:
            df = pd.read_excel(p, sheet_name=0, nrows=TABLE_PREVIEW_ROWS)
        else:
            return None
    except Exception:
        return None

    if df.empty:
        return None
    if len(df.columns) > TABLE_PREVIEW_COLS:
        df = df.iloc[:, :TABLE_PREVIEW_COLS].copy()
    return df


def _format_plan_for_ui(steps: list[Step]) -> str:
    if not steps:
        return "**执行计划**\n\n- 使用默认流程完成分析"
    lines = ["**执行计划**"]
    for index, step in enumerate(steps, start=1):
        label = step.description or step.instruction or "执行分析"
        lines.append(f"{index}. `{step.tool}` {label}")
    return "\n".join(lines)


def _format_step_result_for_ui(step: Step, result: StepResult) -> str:
    parts: list[str] = []
    if result.failed:
        parts.append("状态：失败")
        if result.error:
            parts.append("错误摘要：\n```text\n" + _truncate_text(result.error, 1200) + "\n```")
    else:
        parts.append("状态：完成")

    if result.stdout:
        parts.append("执行输出：\n```text\n" + _truncate_text(result.stdout, 1600) + "\n```")
    if result.files:
        files = "\n".join(f"- {path}" for path in result.files[:8])
        if len(result.files) > 8:
            files += f"\n- ... 另有 {len(result.files) - 8} 个文件"
        parts.append("产物：\n" + files)
    if result.script_path:
        parts.append(f"脚本：`{result.script_path}`")
    return "\n\n".join(parts) if parts else f"{step.description} 已完成。"


def _truncate_text(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "\n..."


def _message_ui_metadata(kind: str) -> dict[str, str]:
    return {"cx_kind": kind}


def _message_ui_marker(kind: str) -> str:
    return UI_KIND_MARKERS.get(kind, "")


def _message_ui_content(kind: str, content: str) -> str:
    marker = _message_ui_marker(kind)
    return f"{marker}\n{content}" if content else marker
