"""Command-line bridge exposing backend typed tools to Pi.

Pi runs as the outer agent runtime. This module keeps all office-data actions
inside the Python backend boundary so Pi does not directly parse raw workbooks
or write artifacts outside the workspace contract.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.agent.artifact_qa import ArtifactExplainer
from app.config import Config
from app.tools.excel_preprocessor import ExcelPreprocessor, NormalizedTable
from app.tools.profiler import Profiler
from app.tools.python_sandbox import PythonSandbox
from app.tools.result_checker import ResultChecker
from app.tools.workbook_ingestor import WorkbookIngestor
from app.workspace import Workspace


class PiToolServiceError(RuntimeError):
    """Raised when a Pi tool-service request is invalid."""


def execute_platform_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    config: Config,
    session_id: str,
    file_path: str | None = None,
) -> dict[str, Any]:
    workspace = Workspace(root=config.workspace_dir, task_id=session_id)
    normalized = _normalize_tool_name(tool_name)

    if normalized == "artifact.list":
        return {"artifacts": workspace.read_artifact_manifest()}

    if normalized == "artifact.inspect":
        artifact = _resolve_artifact(arguments, workspace)
        return {"artifact": ArtifactExplainer().inspect(workspace, artifact)}

    if normalized == "artifact.explain":
        query = str(arguments.get("query") or arguments.get("question") or "")
        artifacts = workspace.read_artifact_manifest()
        return {"explanation": ArtifactExplainer().explain(query, workspace, artifacts)}

    if normalized == "spreadsheet.ingest_workbook":
        source = _source_file(arguments, file_path)
        manifest = WorkbookIngestor().scan(source)
        workspace.save_json("workbook_manifest.json", manifest)
        return {"manifest": manifest}

    if normalized == "spreadsheet.normalize_tables":
        source = _source_file(arguments, file_path)
        manifest = arguments.get("manifest") or workspace.read_json("workbook_manifest.json", None)
        if not manifest:
            manifest = WorkbookIngestor().scan(source)
            workspace.save_json("workbook_manifest.json", manifest)
        result = ExcelPreprocessor().process(source, manifest, Path(workspace.path) / "normalized")
        workspace.save_artifacts(result.tables)
        return {
            "report": result.report,
            "tables": [_table_summary(table) for table in result.tables],
        }

    if normalized == "spreadsheet.profile_tables":
        tables = _normalized_tables_from_manifest(workspace)
        profile = Profiler().profile(tables)
        workspace.save_json("profile.json", profile)
        return {"profile": profile}

    if normalized == "code.run_python_sandboxed":
        code = str(arguments.get("code") or "")
        if not code.strip():
            raise PiToolServiceError("code.run_python_sandboxed requires non-empty code")
        step_id = str(arguments.get("step_id") or "pi_step")
        sandbox = PythonSandbox(
            timeout=config.sandbox_timeout,
            max_memory_mb=config.sandbox_memory_mb,
            max_stdout_chars=config.max_stdout_chars,
        )
        result = sandbox.execute(code, workspace.path, step_id=step_id)
        for output_file in result.output_files:
            workspace.register_artifact(
                path=output_file,
                kind=_infer_artifact_kind(output_file),
                producer_step=step_id,
                producer_tool="code.run_python_sandboxed",
                description=str(arguments.get("description") or "Pi 生成产物"),
                script_path=result.script_path,
                stdout_summary=result.stdout[:1200],
            )
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output_files": result.output_files,
            "script_path": result.script_path,
        }

    if normalized == "result.validate":
        check = ResultChecker().validate(
            step=SimpleNamespace(
                id=str(arguments.get("step_id") or "pi_step"),
                instruction=str(arguments.get("instruction") or ""),
                expected_outputs=_expected_outputs(arguments.get("expected_outputs") or []),
            ),
            exec_result=SimpleNamespace(
                success=bool(arguments.get("success", True)),
                stdout=str(arguments.get("stdout") or ""),
                stderr=str(arguments.get("stderr") or ""),
                output_files=list(arguments.get("files") or arguments.get("output_files") or []),
            ),
            context=SimpleNamespace(step_summaries={}),
            workspace=workspace,
        )
        return {
            "validation": asdict(check)
        }

    raise PiToolServiceError(f"Unsupported tool: {tool_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute Excel Analyzer typed tools for Pi")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--file-path", default="")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--arguments-json", default="{}")
    args = parser.parse_args()

    config = Config(workspace_dir=args.workspace_root)
    arguments = json.loads(args.arguments_json or "{}")
    try:
        result = execute_platform_tool(
            tool_name=args.tool,
            arguments=arguments,
            config=config,
            session_id=args.session_id,
            file_path=args.file_path or None,
        )
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise SystemExit(1) from exc


def _normalize_tool_name(tool_name: str) -> str:
    aliases = {
        "python": "code.run_python_sandboxed",
        "artifact_qa": "artifact.explain",
    }
    return aliases.get(tool_name, tool_name)


def _source_file(arguments: dict[str, Any], file_path: str | None) -> str:
    source = str(arguments.get("file_path") or file_path or "")
    if not source:
        raise PiToolServiceError("Spreadsheet tool requires file_path")
    return source


def _resolve_artifact(arguments: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    artifacts = workspace.read_artifact_manifest()
    query = str(arguments.get("query") or arguments.get("name") or arguments.get("path") or "")
    return ArtifactExplainer().resolve_by_name(query, artifacts)


def _normalized_tables_from_manifest(workspace: Workspace) -> list[NormalizedTable]:
    tables = []
    for item in workspace.read_artifact_manifest():
        if item.get("kind") != "normalized_table":
            continue
        path = str(item.get("path") or "")
        description = str(item.get("description") or Path(path).stem)
        tables.append(
            NormalizedTable(
                table_id=description,
                source_file=str((item.get("inputs") or [""])[0]),
                source_sheet=str((item.get("source_tables") or [description])[0]),
                source_range="",
                parquet_path=path,
                preview_xlsx_path="",
                columns=list(item.get("schema") or []),
                row_count=int(item.get("row_count") or 0),
            )
        )
    if not tables:
        raise PiToolServiceError("No normalized_table artifacts found")
    return tables


def _table_summary(table: NormalizedTable) -> dict[str, Any]:
    return {
        "table_id": table.table_id,
        "path": table.parquet_path,
        "row_count": table.row_count,
        "columns": table.columns,
        "warnings": table.warnings,
    }


def _infer_artifact_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
        return "chart"
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return "excel"
    if suffix in {".csv", ".tsv"}:
        return "csv"
    if suffix in {".md", ".pdf"}:
        return "report"
    return "file"


def _expected_outputs(value: Any) -> list[dict[str, Any]]:
    outputs = []
    for item in list(value or []):
        if isinstance(item, dict):
            outputs.append(item)
        else:
            outputs.append({"path": str(item)})
    return outputs


if __name__ == "__main__":
    main()
