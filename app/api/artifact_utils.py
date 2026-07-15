"""Artifact helpers shared by API routers and run orchestration."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.workspace import Workspace


KIND_BY_SUFFIX = {
    ".png": "chart",
    ".jpg": "chart",
    ".jpeg": "chart",
    ".svg": "chart",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".xls": "excel",
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "data",
    ".pdf": "report",
    ".md": "report",
}


def infer_artifact_kind(path: str | Path) -> str:
    return KIND_BY_SUFFIX.get(Path(path).suffix.lower(), "file")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_urls(artifact_id: str, kind: str) -> dict[str, str | None]:
    table_like = kind in {"excel", "csv", "data", "normalized_table"}
    return {
        "url": f"/api/artifacts/{artifact_id}",
        "preview_url": f"/api/artifacts/{artifact_id}/preview" if table_like else None,
        "sha256_url": f"/api/artifacts/{artifact_id}/sha256",
    }


def resolve_artifact_path(artifact: dict, workspace_root: str | Path) -> Path:
    """Resolve an artifact record's on-disk path with containment enforcement.

    Every artifact path — relative or absolute — must land inside the workspace
    root. Server code populates `path` today, but a bug or a future ingestion
    that lets a crafted value into the DB should not turn the artifact download
    endpoint into an arbitrary-file-read primitive.
    """
    raw_path = Path(artifact["path"])
    root = Path(workspace_root).resolve()
    if raw_path.is_absolute():
        candidate = raw_path.resolve()
    else:
        conversation_id = artifact.get("conversation_id")
        if conversation_id:
            workspace = Workspace(root=workspace_root, task_id=conversation_id)
            candidate = (Path(workspace.path) / raw_path).resolve()
        else:
            candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"artifact path {raw_path} escapes workspace root {root}"
        ) from exc
    return candidate


def artifact_metadata_from_manifest(item: dict | None) -> dict:
    if not item:
        return {}
    keys = {
        "artifact_id",
        "description",
        "producer_step_id",
        "producer_step",
        "producer_tool",
        "inputs",
        "input_artifact_ids",
        "source_tables",
        "script_path",
        "stdout_summary",
        "schema",
        "row_count",
        "chart_metadata",
    }
    return {key: item.get(key) for key in keys if key in item and item.get(key) is not None}
