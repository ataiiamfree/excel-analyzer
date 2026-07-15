"""Artifact download and preview endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.artifact_utils import resolve_artifact_path, sha256_file
from app.api.deps import get_config, get_store
from app.api.persistence.store import Store
from app.api.schemas import TablePreviewOut
from app.config import Config
from app.ui_helpers import _mime_for_path, _table_preview_for_path

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def get_artifact_path(artifact_id: str, store: Store, config: Config) -> tuple[dict, Path]:
    try:
        artifact = store.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="产物不存在") from exc
    try:
        path = resolve_artifact_path(artifact, config.workspace_dir)
    except ValueError as exc:
        # Containment guard tripped — treat as not-found so we never disclose
        # whether the escape target exists on disk.
        raise HTTPException(status_code=404, detail="产物不存在") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件不存在")
    return artifact, path


@router.get("/{artifact_id}")
async def download_artifact(
    artifact_id: str,
    store: Store = Depends(get_store),
    config: Config = Depends(get_config),
) -> FileResponse:
    artifact, path = get_artifact_path(artifact_id, store, config)
    return FileResponse(
        path,
        filename=artifact["name"],
        media_type=_mime_for_path(str(path)),
    )


@router.get("/{artifact_id}/preview", response_model=TablePreviewOut)
async def preview_artifact(
    artifact_id: str,
    store: Store = Depends(get_store),
    config: Config = Depends(get_config),
) -> TablePreviewOut:
    _, path = get_artifact_path(artifact_id, store, config)
    df = _table_preview_for_path(str(path))
    if df is None:
        raise HTTPException(status_code=415, detail="该产物暂不支持表格预览")
    df = df.where(df.notna(), None)
    rows: list[dict[str, Any]] = df.to_dict(orient="records")
    return TablePreviewOut(columns=[str(col) for col in df.columns], rows=rows, row_count=len(rows))


@router.get("/{artifact_id}/sha256")
async def artifact_sha256(
    artifact_id: str,
    store: Store = Depends(get_store),
    config: Config = Depends(get_config),
) -> dict[str, str]:
    artifact, path = get_artifact_path(artifact_id, store, config)
    return {"id": artifact["id"], "sha256": artifact.get("sha256") or sha256_file(path)}
