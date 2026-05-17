from pathlib import Path

from app.workspace import Workspace


def test_workspace_state_and_artifact_manifest(tmp_path: Path):
    workspace = Workspace(root=tmp_path, task_id="task1")
    workspace.write_state(status="executing", current_step="s1")

    state = workspace.read_json("state.json")

    assert state["status"] == "executing"
    assert state["current_step"] == "s1"
    assert workspace.read_artifact_manifest() == []
