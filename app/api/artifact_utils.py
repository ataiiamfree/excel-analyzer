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
    table_like = kind in {"excel", "csv", "data"}
    return {
        "url": f"/api/artifacts/{artifact_id}",
        "preview_url": f"/api/artifacts/{artifact_id}/preview" if table_like else None,
        "sha256_url": f"/api/artifacts/{artifact_id}/sha256",
    }


def resolve_artifact_path(artifact: dict, workspace_root: str | Path) -> Path:
    raw_path = Path(artifact["path"])
    if raw_path.is_absolute():
        return raw_path
    conversation_id = artifact.get("conversation_id")
    if conversation_id:
        workspace = Workspace(root=workspace_root, task_id=conversation_id)
        return Path(workspace.path) / raw_path
    return raw_path
