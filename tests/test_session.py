"""Session management tests."""

from app.session import Session


def test_create_session():
    session = Session.create(file_path="/tmp/test.xlsx")
    assert session.session_id
    assert session.file_path == "/tmp/test.xlsx"
    assert session.tasks == []
    assert not session.is_follow_up


def test_is_follow_up_after_task():
    session = Session.create(file_path="/tmp/test.xlsx")
    assert not session.is_follow_up
    session.update_after_task("t1", findings=["发现A"])
    assert session.is_follow_up


def test_cache_preprocessing():
    session = Session.create(file_path="/tmp/test.xlsx")
    session.cache_preprocessing(
        workbook_manifest={"sheets": []},
        profile={"tables": []},
        normalized_dir="/tmp/normalized",
    )
    assert session.workbook_manifest == {"sheets": []}
    assert session.profile == {"tables": []}
    assert session.normalized_dir == "/tmp/normalized"


def test_build_follow_up_context():
    session = Session.create(file_path="/tmp/test.xlsx")
    session.update_after_task("t1", findings=["IT采购增长12%"], summary_text="分析采购数据")
    session.update_after_task("t2", findings=["办公用品周期偏长"], summary_text="按部门细分")

    ctx = session.build_follow_up_context()
    assert ctx["prior_tasks"] == ["t1", "t2"]
    assert "IT采购增长12%" in ctx["prior_findings"]
    assert "办公用品周期偏长" in ctx["prior_findings"]
    assert "分析采购数据" in ctx["conversation_summary"]
    assert "按部门细分" in ctx["conversation_summary"]


def test_conversation_summary_trimmed():
    session = Session.create(file_path="/tmp/test.xlsx")
    # Add a very long summary
    long_text = "x" * 3000
    session.update_after_task("t1", summary_text=long_text)
    assert len(session.conversation_summary) <= 2000


def test_accumulated_findings_across_tasks():
    session = Session.create(file_path="/tmp/test.xlsx")
    session.update_after_task("t1", findings=["F1", "F2"])
    session.update_after_task("t2", findings=["F3"])
    assert session.accumulated_findings == ["F1", "F2", "F3"]
