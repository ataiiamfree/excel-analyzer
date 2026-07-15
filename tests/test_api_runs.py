"""Tests for the /api/runs headless endpoints."""

from __future__ import annotations

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routers import runs


class _StubConfig:
    def __init__(self, workspace_dir):
        self.workspace_dir = str(workspace_dir)
        self.max_file_size_mb = 100


def test_save_ephemeral_upload_cleans_workspace_on_validation_failure(
    tmp_path, monkeypatch
):
    """Rejected uploads must not leave orphaned workspace directories.

    Regression guard: `Workspace(...)` eagerly mkdirs its skeleton; a burst of
    413/415/422 responses would otherwise pile up empty run_* directories.
    """
    config = _StubConfig(tmp_path / "workspaces")

    def raise_validation(*args, **kwargs):
        raise HTTPException(status_code=415, detail="fake reject")

    monkeypatch.setattr(runs, "save_validated_excel", raise_validation)

    upload = UploadFile(filename="bad.xls", file=BytesIO(b"junk"))
    with pytest.raises(HTTPException) as exc:
        runs.save_ephemeral_upload(upload, config)
    assert exc.value.status_code == 415

    workspace_root = tmp_path / "workspaces"
    # Whatever run_* directory was created must have been wiped again.
    assert not any(workspace_root.iterdir()), (
        f"orphaned workspace children: {list(workspace_root.iterdir())}"
    )
