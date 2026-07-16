import asyncio
import time
from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.api import server
from app.api.routers import conversations


def _event(event_type: str) -> dict:
    return {
        "type": event_type,
        "seq": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def test_websocket_cancel_stops_active_run_without_closing_connection(monkeypatch):
    async def fake_run_conversation_query(*, sender, **kwargs):
        await sender({**_event("run.start"), "message_id": "assistant-1"})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await sender(_event("cancelled"))
            raise

    monkeypatch.setattr(server, "run_conversation_query", fake_run_conversation_query)
    monkeypatch.setattr(server, "get_store", lambda: object())
    monkeypatch.setattr(server, "get_session_registry", lambda: object())

    with TestClient(server.app).websocket_connect("/ws/conversations/test") as websocket:
        websocket.send_json({"type": "user_message", "content": "开始分析"})
        assert websocket.receive_json()["type"] == "run.start"

        websocket.send_json({"type": "cancel"})
        assert websocket.receive_json()["type"] == "cancelled"

        websocket.send_json({"type": "cancel"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["error_kind"] == "no_active_run"


def test_websocket_rejects_invalid_message_without_closing_connection(monkeypatch):
    monkeypatch.setattr(server, "get_store", lambda: object())
    monkeypatch.setattr(server, "get_session_registry", lambda: object())

    with TestClient(server.app).websocket_connect("/ws/conversations/test") as websocket:
        websocket.send_json({"type": "unknown"})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["error_kind"] == "invalid_message"

        websocket.send_json({"type": "cancel"})
        assert websocket.receive_json()["error_kind"] == "no_active_run"


def test_replacing_file_preserves_conversation_title(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()

    class FakeStore:
        def __init__(self):
            self.row = {
                "id": "conversation-1",
                "title": "按季度分析销售趋势",
                "file_name": "old.xlsx",
                "file_size": 10,
                "sheet_count": 1,
                "row_count": 2,
                "created_at": now,
                "updated_at": now,
                "starred": False,
                "archived_at": None,
            }
            self.updated_values = {}

        def get_conversation(self, conversation_id):
            assert conversation_id == "conversation-1"
            return self.row

        def update_conversation(self, conversation_id, **values):
            assert conversation_id == "conversation-1"
            self.updated_values = values
            self.row = {**self.row, **values}
            return self.row

    class FakeSessions:
        def replace_file(self, conversation_id, file_path):
            assert conversation_id == "conversation-1"
            assert file_path == "/tmp/new.xlsx"

    store = FakeStore()
    monkeypatch.setattr(
        conversations,
        "save_upload_to_workspace",
        lambda *_args, **_kwargs: ("/tmp/new.xlsx", 20, 2, 30),
    )

    result = asyncio.run(
        conversations.replace_file(
            "conversation-1",
            UploadFile(filename="new.xlsx", file=BytesIO(b"workbook")),
            store=store,
            config=object(),
            sessions=FakeSessions(),
        )
    )

    assert result.title == "按季度分析销售趋势"
    assert result.file_name == "new.xlsx"
    assert "title" not in store.updated_values


def _write_index(web_dist):
    web_dist.mkdir(parents=True, exist_ok=True)
    (web_dist / "assets").mkdir(exist_ok=True)
    (web_dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")


def test_spa_fallback_serves_index_for_unknown_route(tmp_path, monkeypatch):
    web_dist = tmp_path / "web-dist"
    _write_index(web_dist)
    monkeypatch.setattr(server.config, "web_dist_dir", str(web_dist))
    from importlib import reload
    from app.api import server as _server
    reload(_server)
    try:
        response = TestClient(_server.app).get("/does-not-exist")
        assert response.status_code == 200
        assert "<html>" in response.text
    finally:
        # restore original module for other tests
        reload(server)


def test_spa_fallback_rejects_encoded_traversal(tmp_path, monkeypatch):
    """SPA fallback must never leak files outside the built SPA directory."""
    web_dist = tmp_path / "web-dist"
    _write_index(web_dist)
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET-DEEPSEEK-API-KEY", encoding="utf-8")

    monkeypatch.setattr(server.config, "web_dist_dir", str(web_dist))
    from importlib import reload
    from app.api import server as _server
    reload(_server)
    client = TestClient(_server.app)
    try:
        # url-decoded `..` (which Starlette normalizes) and url-encoded `..`
        # (which Starlette forwards raw) both need to be contained.
        for attack in [
            "/%2e%2e/secret.txt",
            "/..%2fsecret.txt",
            "/foo/..%2f..%2fsecret.txt",
            "/%2e%2e/%2e%2e/etc/passwd",
        ]:
            response = client.get(attack)
            # Either 200 with SPA index or something benign — never the secret.
            assert "SECRET-DEEPSEEK-API-KEY" not in response.text, (
                f"path traversal succeeded for {attack!r}"
            )
    finally:
        reload(server)


class _FakeWsManager:
    """Minimal ConnectionManager stand-in for router unit tests."""

    def __init__(self, active_run: bool = False) -> None:
        self._active_run = active_run
        self.checked = False

    def has_active_run(self, conversation_id: str) -> bool:
        self.checked = True
        assert conversation_id == "conversation-1"
        return self._active_run


class _FakeDeleteStore:
    def __init__(self, conversation_id: str = "conversation-1") -> None:
        self.conversation_id = conversation_id
        self.deleted = False

    def get_conversation(self, conversation_id):
        assert conversation_id == self.conversation_id
        return {"id": conversation_id}

    def delete_conversation(self, conversation_id):
        assert conversation_id == self.conversation_id
        self.deleted = True


class _FakeSessionRegistry:
    def __init__(self) -> None:
        self.deleted_ids: list[str] = []

    def delete(self, conversation_id: str) -> None:
        self.deleted_ids.append(conversation_id)


def test_delete_conversation_removes_workspace_and_session(tmp_path, monkeypatch):
    """Happy path: no active WS → conversation, workspace and session all cleared."""
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "conversation-1" / "raw").mkdir(parents=True)
    (workspace_root / "conversation-1" / "raw" / "book.xlsx").write_text("x")

    class _Cfg:
        workspace_dir = str(workspace_root)

    store = _FakeDeleteStore()
    sessions = _FakeSessionRegistry()
    manager = _FakeWsManager(active_run=False)

    asyncio.run(
        conversations.delete_conversation(
            "conversation-1",
            store=store,
            config=_Cfg(),
            sessions=sessions,
            manager=manager,
        )
    )

    assert manager.checked, "has_active_run must be consulted before delete"
    assert store.deleted, "store.delete_conversation must be called"
    assert sessions.deleted_ids == ["conversation-1"], (
        "SessionRegistry.delete must be called so long-running processes don't leak"
    )
    assert not (workspace_root / "conversation-1").exists(), (
        "workspace directory must be removed"
    )


def test_delete_conversation_rejects_when_run_active(tmp_path):
    """P1-6: refuse to delete while an analysis is actually executing.

    Regression guard: previously the router blindly rmtree'd the workspace,
    which killed the running sandbox script in the other tab with an opaque
    FileNotFoundError.
    """
    from fastapi import HTTPException

    workspace_root = tmp_path / "workspaces"
    (workspace_root / "conversation-1").mkdir(parents=True)

    class _Cfg:
        workspace_dir = str(workspace_root)

    store = _FakeDeleteStore()
    sessions = _FakeSessionRegistry()
    manager = _FakeWsManager(active_run=True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            conversations.delete_conversation(
                "conversation-1",
                store=store,
                config=_Cfg(),
                sessions=sessions,
                manager=manager,
            )
        )

    assert exc.value.status_code == 409
    assert "正在运行" in exc.value.detail
    assert not store.deleted, "store must not be touched while a run is active"
    assert sessions.deleted_ids == [], "session must not be released while a run is active"
    assert (workspace_root / "conversation-1").exists(), (
        "workspace must survive a rejected delete"
    )


def _delete_via_router(conversation_id: str, workspace_root, store, sessions) -> None:
    """Run the real delete endpoint against the real ConnectionManager singleton."""

    class _Cfg:
        workspace_dir = str(workspace_root)

    asyncio.run(
        conversations.delete_conversation(
            conversation_id,
            store=store,
            config=_Cfg(),
            sessions=sessions,
            manager=server.manager,
        )
    )


def test_delete_allowed_while_ws_connected_but_idle(tmp_path, monkeypatch):
    """P1-6 修正回归：空闲会话页（WS 已连接、无运行中分析）必须可删除。

    修正前 `has_active` 把任意 WS 连接当成"分析运行中"，前端每个打开的
    会话页都挂着 WS，导致空闲页面也删不掉。
    """
    monkeypatch.setattr(server, "get_store", lambda: object())
    monkeypatch.setattr(server, "get_session_registry", lambda: object())

    workspace_root = tmp_path / "workspaces"
    (workspace_root / "conv-idle").mkdir(parents=True)
    store = _FakeDeleteStore("conv-idle")
    sessions = _FakeSessionRegistry()

    with TestClient(server.app).websocket_connect("/ws/conversations/conv-idle"):
        assert server.manager.has_connections("conv-idle")
        assert not server.manager.has_active_run("conv-idle")
        _delete_via_router("conv-idle", workspace_root, store, sessions)

    assert store.deleted, "idle-but-connected conversation must be deletable"
    assert sessions.deleted_ids == ["conv-idle"]
    assert not (workspace_root / "conv-idle").exists()


def test_delete_rejected_while_analysis_running(tmp_path, monkeypatch):
    """P1-6 回归：分析真正执行期间删除必须返回 409。"""
    from fastapi import HTTPException

    async def fake_run_conversation_query(*, sender, **kwargs):
        await sender({**_event("run.start"), "message_id": "assistant-1"})
        await asyncio.Event().wait()

    monkeypatch.setattr(server, "run_conversation_query", fake_run_conversation_query)
    monkeypatch.setattr(server, "get_store", lambda: object())
    monkeypatch.setattr(server, "get_session_registry", lambda: object())

    workspace_root = tmp_path / "workspaces"
    (workspace_root / "conv-run").mkdir(parents=True)
    store = _FakeDeleteStore("conv-run")
    sessions = _FakeSessionRegistry()

    with TestClient(server.app).websocket_connect("/ws/conversations/conv-run") as websocket:
        websocket.send_json({"type": "user_message", "content": "开始分析"})
        assert websocket.receive_json()["type"] == "run.start"
        assert server.manager.has_active_run("conv-run")

        with pytest.raises(HTTPException) as exc:
            _delete_via_router("conv-run", workspace_root, store, sessions)

        assert exc.value.status_code == 409
        assert "正在运行" in exc.value.detail

    assert not store.deleted
    assert (workspace_root / "conv-run").exists()


def test_delete_allowed_after_cancel_or_completion(tmp_path, monkeypatch):
    """P1-6 回归：分析被取消或正常完成后，会话必须恢复可删除。"""

    async def fake_run_conversation_query(*, query, sender, **kwargs):
        await sender({**_event("run.start"), "message_id": "assistant-1"})
        if "阻塞" in query:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await sender(_event("cancelled"))
                raise
        else:
            await sender(_event("run.complete"))

    monkeypatch.setattr(server, "run_conversation_query", fake_run_conversation_query)
    monkeypatch.setattr(server, "get_store", lambda: object())
    monkeypatch.setattr(server, "get_session_registry", lambda: object())

    workspace_root = tmp_path / "workspaces"

    # 取消后可删除
    (workspace_root / "conv-cancel").mkdir(parents=True)
    store = _FakeDeleteStore("conv-cancel")
    sessions = _FakeSessionRegistry()
    with TestClient(server.app).websocket_connect("/ws/conversations/conv-cancel") as websocket:
        websocket.send_json({"type": "user_message", "content": "阻塞分析"})
        assert websocket.receive_json()["type"] == "run.start"
        websocket.send_json({"type": "cancel"})
        assert websocket.receive_json()["type"] == "cancelled"
        # 第二次 cancel 的 no_active_run 应答确保 handler 已完整 await 掉
        # 被取消的任务（含 finally 里的 end_run），避免时序抖动。
        websocket.send_json({"type": "cancel"})
        assert websocket.receive_json()["error_kind"] == "no_active_run"

        assert not server.manager.has_active_run("conv-cancel")
        _delete_via_router("conv-cancel", workspace_root, store, sessions)
    assert store.deleted, "conversation must be deletable after cancelling the run"

    # 正常完成后可删除
    (workspace_root / "conv-done").mkdir(parents=True)
    store = _FakeDeleteStore("conv-done")
    sessions = _FakeSessionRegistry()
    with TestClient(server.app).websocket_connect("/ws/conversations/conv-done") as websocket:
        websocket.send_json({"type": "user_message", "content": "普通分析"})
        assert websocket.receive_json()["type"] == "run.start"
        assert websocket.receive_json()["type"] == "run.complete"
        # run.complete 发出后任务还差一个调度周期才执行 finally 里的
        # end_run（run 跑在 TestClient 的后台事件循环线程），轮询等待归零。
        deadline = time.monotonic() + 2
        while server.manager.has_active_run("conv-done") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not server.manager.has_active_run("conv-done")
        _delete_via_router("conv-done", workspace_root, store, sessions)
    assert store.deleted, "conversation must be deletable after the run completes"


def test_spa_fallback_rejects_absolute_paths(tmp_path, monkeypatch):
    web_dist = tmp_path / "web-dist"
    _write_index(web_dist)
    monkeypatch.setattr(server.config, "web_dist_dir", str(web_dist))
    from importlib import reload
    from app.api import server as _server
    reload(_server)
    try:
        # Absolute URL segments should never escape the SPA either.
        response = TestClient(_server.app).get("//etc/hosts")
        assert "127.0.0.1" not in response.text
        assert "<html>" in response.text
    finally:
        reload(server)
