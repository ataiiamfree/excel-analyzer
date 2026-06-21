from pathlib import Path

from app.agent.pi_tool_service import execute_platform_tool
from app.config import Config
from app.workspace import Workspace


def test_pi_tool_service_explains_artifact(tmp_path):
    config = Config(workspace_dir=str(tmp_path))
    workspace = Workspace(root=config.workspace_dir, task_id="s1")
    workspace.register_artifact(
        path="output/trend.png",
        kind="chart",
        producer_step="s1",
        producer_tool="python",
        description="趋势图",
        source_tables=["巡检记录"],
        stdout_summary="温度异常 6 点。",
    )

    result = execute_platform_tool(
        tool_name="artifact.explain",
        arguments={"query": "解释 trend.png"},
        config=config,
        session_id="s1",
    )

    assert "trend.png" in result["explanation"]
    assert "巡检记录" in result["explanation"]
    assert "温度异常 6 点" in result["explanation"]


def test_pi_tool_service_runs_sandbox_and_registers_outputs(tmp_path):
    config = Config(workspace_dir=str(tmp_path), sandbox_timeout=10)
    Workspace(root=config.workspace_dir, task_id="s1")
    code = """
from pathlib import Path
Path("output").mkdir(exist_ok=True)
Path("output/pi_result.csv").write_text("a,b\\n1,2\\n", encoding="utf-8")
print("generated")
"""

    result = execute_platform_tool(
        tool_name="code.run_python_sandboxed",
        arguments={"code": code, "step_id": "pi_s1", "description": "Pi 结果表"},
        config=config,
        session_id="s1",
    )

    assert result["success"] is True
    assert result["output_files"] == ["output/pi_result.csv"]
    manifest = Workspace(root=config.workspace_dir, task_id="s1").read_artifact_manifest()
    assert manifest[-1]["path"] == "output/pi_result.csv"
    assert manifest[-1]["producer_tool"] == "code.run_python_sandboxed"
    assert Path(tmp_path, "s1", "output", "pi_result.csv").exists()


def test_pi_tool_service_validates_string_expected_outputs(tmp_path):
    config = Config(workspace_dir=str(tmp_path))
    workspace = Workspace(root=config.workspace_dir, task_id="s1")
    output_dir = Path(workspace.path) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.csv").write_text("ok", encoding="utf-8")

    result = execute_platform_tool(
        tool_name="result.validate",
        arguments={
            "stdout": "done",
            "files": ["output/result.csv"],
            "expected_outputs": ["output/result.csv"],
        },
        config=config,
        session_id="s1",
    )

    assert result["validation"]["status"] == "passed"
