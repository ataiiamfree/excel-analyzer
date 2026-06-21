from pathlib import Path
from types import SimpleNamespace

from app.agent.types import StepResult
from app.tools.result_checker import ResultChecker


def _make_step(step_id="s1", expected_outputs=None, instruction="分析数据"):
    return SimpleNamespace(
        id=step_id,
        expected_outputs=expected_outputs or [],
        instruction=instruction,
    )


def _make_result(success=True, stdout="结果正常", stderr="", output_files=None):
    return SimpleNamespace(
        success=success,
        stdout=stdout,
        stderr=stderr,
        output_files=output_files or [],
    )


def _make_workspace(tmp_path):
    return SimpleNamespace(
        path=str(tmp_path),
        list_files=lambda: [],
    )


def _make_context():
    return SimpleNamespace(step_summaries={})


def test_all_pass(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(), _make_result(), _make_context(), _make_workspace(tmp_path)
    )
    assert result.status == "passed"
    assert not result.failed


def test_step_result_contract_passes(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(),
        StepResult(stdout="分析完成: 总计 100 行", files=[]),
        _make_context(),
        _make_workspace(tmp_path),
    )
    assert result.status == "passed"


def test_process_failure(tmp_path):
    checker = ResultChecker()
    result = checker.validate(
        _make_step(),
        _make_result(success=False, stderr="ImportError"),
        _make_context(),
        _make_workspace(tmp_path),
    )
    assert result.status == "failed"
    assert any(c.name == "process_success" and c.status == "failed" for c in result.checks)


def test_empty_stdout_warning(tmp_path):
    checker = ResultChecker()
    step = _make_step(expected_outputs=[{"path": "output/data.xlsx"}])
    result = checker.validate(
        step, _make_result(stdout=""), _make_context(), _make_workspace(tmp_path)
    )
    assert any(c.name == "stdout_not_empty" and c.status == "warning" for c in result.checks)


def test_output_files_readable(tmp_path):
    # 创建一个空文件（应触发警告）
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "empty.csv").write_text("")
    (output_dir / "good.csv").write_text("a,b\n1,2\n")

    checker = ResultChecker()
    exec_result = _make_result(output_files=["output/empty.csv", "output/good.csv"])
    result = checker.validate(
        _make_step(), exec_result, _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    assert any(c.name == "output_files_readable" and c.status == "failed" for c in result.checks)


def test_basic_invariants_export_warning(tmp_path):
    """导出指令但本步骤无 output 产物时应失败，触发自动修复。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="导出明细数据到 Excel"),
        _make_result(),
        _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    failures = [c for c in result.checks if c.name == "export_has_output"]
    assert len(failures) == 1
    assert failures[0].status == "failed"
    assert result.status == "failed"


def test_basic_invariants_export_passes_with_current_step_output(tmp_path):
    """导出指令存在当前步骤产物时不应误报。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "data.csv").write_text("a,b\n1,2\n")

    checker = ResultChecker()
    result = checker.validate(
        _make_step(instruction="导出明细数据到 Excel"),
        _make_result(output_files=["output/data.csv"]),
        _make_context(),
        SimpleNamespace(path=str(tmp_path), list_files=lambda: []),
    )
    assert not any(c.name == "export_has_output" for c in result.checks)
    assert result.status == "passed"
