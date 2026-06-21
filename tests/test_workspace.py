from pathlib import Path

from app.workspace import Workspace


def test_workspace_state_and_artifact_manifest(tmp_path: Path):
    workspace = Workspace(root=tmp_path, task_id="task1")
    # 验证初始状态
    state = workspace.read_json("state.json")
    assert state["status"] == "pending"
    assert state["started_at"] is not None
    assert state["retry_count"] == 0

    workspace.write_state(status="executing", current_step="s1")
    state = workspace.read_json("state.json")
    assert state["status"] == "executing"
    assert state["current_step"] == "s1"
    assert workspace.read_artifact_manifest() == []


def test_workspace_does_not_overwrite_existing_state(tmp_path: Path):
    ws1 = Workspace(root=tmp_path, task_id="task_resume")
    ws1.write_state(status="executing", current_step="s3")

    # 重新构造同一 task_id 的 Workspace，不应覆写状态
    ws2 = Workspace(root=tmp_path, task_id="task_resume")
    state = ws2.read_json("state.json")
    assert state["status"] == "executing"
    assert state["current_step"] == "s3"


def test_workspace_cancel(tmp_path: Path):
    workspace = Workspace(root=tmp_path, task_id="task_cancel")
    assert workspace.is_cancel_requested() is False
    workspace.request_cancel()
    assert workspace.is_cancel_requested() is True


def test_workspace_register_artifact(tmp_path: Path):
    workspace = Workspace(root=tmp_path, task_id="task_art")
    workspace.register_artifact(
        path="output/chart.png",
        kind="chart",
        producer_step="s1",
        description="销售趋势图",
    )
    manifest = workspace.read_artifact_manifest()
    assert len(manifest) == 1
    assert manifest[0]["kind"] == "chart"
    assert manifest[0]["artifact_id"].startswith("art_")
    assert manifest[0]["producer_step_id"] == "s1"
    assert manifest[0]["producer_tool"] == "python"
    assert manifest[0]["created_at"] is not None


def test_workspace_directory_structure(tmp_path: Path):
    workspace = Workspace(root=tmp_path, task_id="task_dirs")
    for dirname in ("raw", "normalized", "output", "scripts", "logs"):
        assert (workspace.path / dirname).is_dir()


def test_workspace_cleanup(tmp_path: Path):
    # 创建 7 个任务目录
    for i in range(7):
        Workspace(root=tmp_path, task_id=f"task_{i}")

    ws = Workspace(root=tmp_path, task_id="task_current")
    removed = ws.cleanup(keep_recent=3)
    remaining = [d.name for d in tmp_path.iterdir() if d.is_dir()]
    assert len(remaining) == 3
    assert len(removed) >= 5
