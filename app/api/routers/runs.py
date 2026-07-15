"""Headless REST run endpoints for eval and CI."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_config, get_run_registry, get_store
from app.api.persistence.store import Store
from app.api.uploads import save_validated_excel
from app.api.ws.runner import run_ephemeral_query
from app.config import Config
from app.workspace import Workspace

router = APIRouter(prefix="/api/runs", tags=["runs"])


def save_ephemeral_upload(upload: UploadFile, config: Config) -> str:
    run_id = f"run_{uuid.uuid4().hex}"
    workspace = Workspace(root=config.workspace_dir, task_id=run_id)
    target = Path(workspace.path) / "raw" / Path(upload.filename or "upload.xlsx").name
    try:
        save_validated_excel(upload, target, max_size_mb=config.max_file_size_mb)
    except HTTPException:
        # Workspace already mkdir'd its skeleton; wipe it so a burst of
        # rejected uploads (413/415/422) does not leave orphaned directories.
        shutil.rmtree(Path(config.workspace_dir) / run_id, ignore_errors=True)
        raise
    return str(target.resolve())


@router.post("")
async def run_once(
    file: Annotated[UploadFile, File()],
    query: Annotated[str, Form()],
    params: Annotated[str | None, Form()] = None,
    ephemeral: Annotated[bool, Form()] = True,
    store: Store = Depends(get_store),
    config: Config = Depends(get_config),
):
    _ = params, ephemeral
    file_path = save_ephemeral_upload(file, config)
    return await run_ephemeral_query(store=store, config=config, file_path=file_path, query=query)


@router.get("/{run_id}")
async def get_run_status(run_id: str, registry=Depends(get_run_registry)):
    state = registry.get_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run 不存在或已过期")
    return {"run_id": run_id, **state}


@router.delete("/{run_id}", status_code=204)
async def cancel_run(run_id: str, registry=Depends(get_run_registry)) -> None:
    if not registry.cancel(run_id):
        raise HTTPException(status_code=404, detail="run 不存在或已结束")
