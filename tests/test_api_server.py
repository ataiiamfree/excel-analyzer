import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api import server


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
