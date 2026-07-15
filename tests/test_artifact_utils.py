"""Tests for artifact path resolution and containment enforcement."""

from __future__ import annotations

import pytest

from app.api.artifact_utils import resolve_artifact_path


def test_resolve_relative_path_inside_workspace(tmp_path):
    workspace_root = tmp_path / "workspaces"
    conv_dir = workspace_root / "conv-1"
    (conv_dir / "output").mkdir(parents=True)
    file_path = conv_dir / "output" / "report.md"
    file_path.write_text("hi", encoding="utf-8")

    resolved = resolve_artifact_path(
        {"path": "output/report.md", "conversation_id": "conv-1"},
        workspace_root,
    )

    assert resolved == file_path.resolve()


def test_resolve_absolute_path_inside_workspace_is_allowed(tmp_path):
    workspace_root = tmp_path / "workspaces"
    conv_dir = workspace_root / "conv-1"
    (conv_dir / "output").mkdir(parents=True)
    file_path = conv_dir / "output" / "chart.png"
    file_path.write_text("img", encoding="utf-8")

    resolved = resolve_artifact_path(
        {"path": str(file_path), "conversation_id": "conv-1"},
        workspace_root,
    )

    assert resolved == file_path.resolve()


def test_resolve_rejects_relative_escape(tmp_path):
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "conv-1").mkdir(parents=True)
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes workspace root"):
        resolve_artifact_path(
            {"path": "../../outside.txt", "conversation_id": "conv-1"},
            workspace_root,
        )


def test_resolve_rejects_absolute_path_outside_workspace(tmp_path):
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(parents=True)
    (tmp_path / "leak.env").write_text("SECRET=x", encoding="utf-8")

    # A future bug could put an absolute crafted path into the DB. The
    # resolver must refuse regardless of where the path points.
    with pytest.raises(ValueError, match="escapes workspace root"):
        resolve_artifact_path(
            {"path": str(tmp_path / "leak.env"), "conversation_id": "conv-1"},
            workspace_root,
        )


def test_resolve_without_conversation_still_enforced(tmp_path):
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    with pytest.raises(ValueError, match="escapes workspace root"):
        resolve_artifact_path(
            {"path": "../etc/passwd"},
            workspace_root,
        )
