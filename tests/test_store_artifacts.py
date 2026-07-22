"""Artifact 登记的幂等性与历史重复数据兼容测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

from app.api.persistence.store import Store, utc_now_iso


def _make_store(tmp_path) -> Store:
    store = Store(tmp_path / "chat.sqlite3")
    store.create_conversation(
        title="测试会话",
        file_name="book.xlsx",
        file_size=1,
        local_file_path="/tmp/book.xlsx",
        conversation_id="conv-1",
    )
    return store


def _register(store: Store, *, size: int = 10, message_id: str | None = None, path: str = "output/result.csv"):
    return store.create_artifact(
        conversation_id="conv-1",
        message_id=message_id,
        path=path,
        kind="table",
        name="result.csv",
        size=size,
        sha256=f"sha-{size}",
        metadata={"row_count": size},
    )


def _artifact_row_count(store: Store) -> int:
    return store._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]


def test_reregistering_same_path_reuses_row_and_id(tmp_path):
    """follow-up 重跑同一 path 不再新增行：复用 id，只刷新内容属性。"""
    store = _make_store(tmp_path)
    first = _register(store, size=10, message_id="msg-1")
    second = _register(store, size=99, message_id="msg-2")

    assert second["id"] == first["id"]
    assert second["created_at"] == first["created_at"], "created_at 保持首次登记时间"
    assert second["size"] == 99
    assert second["message_id"] == "msg-2"
    assert _artifact_row_count(store) == 1
    assert len(store.list_artifacts("conv-1")) == 1


def test_different_paths_and_conversations_stay_separate(tmp_path):
    store = _make_store(tmp_path)
    store.create_conversation(
        title="另一会话",
        file_name="b.xlsx",
        file_size=1,
        local_file_path="/tmp/b.xlsx",
        conversation_id="conv-2",
    )
    a = _register(store, path="output/a.csv")
    b = _register(store, path="output/b.csv")
    other = store.create_artifact(
        conversation_id="conv-2",
        path="output/a.csv",
        kind="table",
        name="a.csv",
        size=5,
    )

    assert len({a["id"], b["id"], other["id"]}) == 3
    assert _artifact_row_count(store) == 3


def test_legacy_duplicate_rows_survive_and_newest_becomes_carrier(tmp_path):
    """迁移兼容：旧版盲 INSERT 留下的重复行不删除，历史 id 保持可解析。"""
    store = _make_store(tmp_path)
    # 模拟旧版行为：同 path 直接插入两行（绕过幂等逻辑，用显式 artifact_id）
    legacy_ids = []
    for i in range(2):
        aid = f"art_legacy_{i}_{uuid.uuid4().hex[:8]}"
        store._conn.execute(
            """
            INSERT INTO artifacts
                (id, conversation_id, message_id, path, kind, name, size, sha256, metadata, created_at)
            VALUES (?, 'conv-1', ?, 'output/result.csv', 'table', 'result.csv', ?, NULL, '{}', ?)
            """,
            (aid, f"msg-{i}", i + 1, utc_now_iso()),
        )
        legacy_ids.append(aid)
    store._conn.commit()

    # 重新打开 store：init_db 的索引迁移在已有重复数据上不得失败
    store2 = Store(tmp_path / "chat.sqlite3")
    updated = store2.create_artifact(
        conversation_id="conv-1",
        message_id="msg-new",
        path="output/result.csv",
        kind="table",
        name="result.csv",
        size=42,
    )

    assert updated["id"] == legacy_ids[-1], "最新一行成为承载行"
    assert updated["size"] == 42
    # 两个历史 id 都仍可通过 get_artifact 解析（消息 payload 引用不被破坏）
    for aid in legacy_ids:
        assert store2.get_artifact(aid)["id"] == aid
    assert store2._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 2, "不新增行也不删旧行"


def test_explicit_artifact_id_still_inserts(tmp_path):
    """显式传 artifact_id 保持旧语义：直接插入，不参与幂等复用。"""
    store = _make_store(tmp_path)
    _register(store)
    explicit = store.create_artifact(
        conversation_id="conv-1",
        path="output/result.csv",
        kind="table",
        name="result.csv",
        size=7,
        artifact_id="art_explicit",
    )
    assert explicit["id"] == "art_explicit"
    assert _artifact_row_count(store) == 2


def test_registration_without_conversation_never_dedupes(tmp_path):
    store = Store(tmp_path / "chat.sqlite3")
    a = store.create_artifact(path="output/x.csv", kind="table", name="x.csv", size=1)
    b = store.create_artifact(path="output/x.csv", kind="table", name="x.csv", size=2)
    assert a["id"] != b["id"]


def test_concurrent_store_connections_register_one_artifact(tmp_path):
    """数据库级事务必须覆盖查找与插入，不能只依赖单实例 RLock。"""
    db_path = tmp_path / "chat.sqlite3"
    root = Store(db_path)
    root.create_conversation(
        title="并发测试",
        file_name="book.xlsx",
        file_size=1,
        local_file_path="/tmp/book.xlsx",
        conversation_id="conv-race",
    )

    stores = [Store(db_path) for _ in range(16)]
    barrier = threading.Barrier(len(stores))

    def register(store: Store) -> str:
        barrier.wait()
        return store.create_artifact(
            conversation_id="conv-race",
            path="output/same.csv",
            kind="table",
            name="same.csv",
            size=1,
        )["id"]

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        artifact_ids = list(pool.map(register, stores))

    assert len(set(artifact_ids)) == 1
    assert root._conn.execute(
        """
        SELECT COUNT(*) FROM artifacts
        WHERE conversation_id = ? AND path = ?
        """,
        ("conv-race", "output/same.csv"),
    ).fetchone()[0] == 1
