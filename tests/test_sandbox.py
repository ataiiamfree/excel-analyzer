import sys

import pytest

from app.tools.python_sandbox import PythonSandbox, SandboxPolicyError


def test_banned_fragment_detected():
    sandbox = PythonSandbox()
    with pytest.raises(SandboxPolicyError, match="os.system"):
        sandbox._static_check("os.system('ls')")


def test_import_bypass_blocked():
    sandbox = PythonSandbox()
    with pytest.raises(SandboxPolicyError, match="__import__"):
        sandbox._static_check('__import__("os").system("ls")')


def test_eval_blocked_by_ast():
    sandbox = PythonSandbox()
    with pytest.raises(SandboxPolicyError, match="eval"):
        sandbox._static_check('result = eval("1+1")')


def test_exec_blocked_by_ast():
    sandbox = PythonSandbox()
    with pytest.raises(SandboxPolicyError, match="exec"):
        sandbox._static_check('exec("import os")')


def test_absolute_path_open_blocked():
    sandbox = PythonSandbox()
    with pytest.raises(SandboxPolicyError, match="绝对路径"):
        sandbox._static_check('f = open("/etc/passwd")')


def test_safe_code_passes():
    sandbox = PythonSandbox()
    # 应该不抛异常
    sandbox._static_check("""
import pandas as pd
df = pd.read_parquet("normalized/data.parquet")
print(df.describe())
df.to_excel("output/result.xlsx", index=False)
""")


def test_execute_safe_script(tmp_path):
    sandbox = PythonSandbox(timeout=10)
    result = sandbox.execute(
        code='print("hello")',
        workdir=tmp_path,
        step_id="s1",
        attempt=0,
    )
    assert result.success is True
    assert "hello" in result.stdout


def test_default_python_executable_matches_current_runtime():
    sandbox = PythonSandbox()
    assert sandbox.python_executable == sys.executable


def test_execute_timeout(tmp_path):
    sandbox = PythonSandbox(timeout=2)
    result = sandbox.execute(
        code='import time; time.sleep(10)',
        workdir=tmp_path,
        step_id="s1",
        attempt=0,
    )
    assert result.success is False
    assert "超时" in result.stderr
