import asyncio
from datetime import datetime, timezone
from io import BytesIO

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
