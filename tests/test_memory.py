"""Memory (cross-session schema matching and history) tests."""

import tempfile
from pathlib import Path

from app.memory import Memory


def _make_memory(tmp_path: str | None = None) -> Memory:
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    return Memory(path=Path(tmp_path) / "user_memory.json")


def test_save_and_match_schema():
    mem = _make_memory()
    cols = ["采购日期", "供应商", "金额", "部门"]
    mem.save_schema(cols, label="采购表", common_dimensions=["部门", "供应商"])

    match = mem.match_schema(["采购日期", "供应商", "金额", "部门", "备注"])
    assert match is not None
    assert match["label"] == "采购表"


def test_no_match_when_low_overlap():
    mem = _make_memory()
    mem.save_schema(["A", "B", "C"], label="表A")
    match = mem.match_schema(["X", "Y", "Z"])
    assert match is None


def test_update_existing_schema_on_high_overlap():
    mem = _make_memory()
    mem.save_schema(["A", "B", "C", "D", "E"], label="v1")
    mem.save_schema(["A", "B", "C", "D", "E"], label="v2")  # 100% overlap → update

    schemas = mem._data["schemas"]
    assert len(schemas) == 1
    assert schemas[0]["label"] == "v2"


def test_add_session_record():
    mem = _make_memory()
    mem.add_session_record("s1", "file.xlsx", ["分析数据"], findings=["发现A"])
    mem.add_session_record("s2", "file2.xlsx", ["统计"], findings=["发现B"])

    recent = mem.recent_sessions(10)
    assert len(recent) == 2
    assert recent[0]["session_id"] == "s1"
    assert recent[1]["session_id"] == "s2"


def test_history_capped_at_max():
    mem = _make_memory()
    for i in range(60):
        mem.add_session_record(f"s{i}", f"f{i}.xlsx", [f"q{i}"])

    assert len(mem._data["history"]) == 50


def test_persistence_across_loads():
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "user_memory.json"

    mem1 = Memory(path=path)
    mem1.save_schema(["A", "B"], label="test")
    mem1.add_session_record("s1", "f.xlsx", ["q"])

    mem2 = Memory(path=path)
    assert mem2.match_schema(["A", "B"]) is not None
    assert len(mem2.recent_sessions()) == 1
