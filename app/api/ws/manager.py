"""Minimal connection manager for conversation WebSockets."""

from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Tracks two distinct facts per conversation:

    - *connected*: a client WS is open (the frontend keeps one per open
      conversation page, even when idle);
    - *active run*: an analysis task started over that WS is still executing.

    Only the second must block deletion — an idle page is safe to delete.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._active_runs: dict[str, int] = defaultdict(int)

    async def connect(self, conversation_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[conversation_id].add(websocket)

    def disconnect(self, conversation_id: str, websocket: WebSocket) -> None:
        self._connections[conversation_id].discard(websocket)
        if not self._connections[conversation_id]:
            self._connections.pop(conversation_id, None)

    async def send_json(self, conversation_id: str, payload: dict) -> None:
        for websocket in list(self._connections.get(conversation_id, set())):
            await websocket.send_json(payload)

    def has_connections(self, conversation_id: str) -> bool:
        """True while any client WS is still connected for the conversation."""
        return bool(self._connections.get(conversation_id))

    def begin_run(self, conversation_id: str) -> None:
        self._active_runs[conversation_id] += 1

    def end_run(self, conversation_id: str) -> None:
        remaining = self._active_runs[conversation_id] - 1
        if remaining > 0:
            self._active_runs[conversation_id] = remaining
        else:
            self._active_runs.pop(conversation_id, None)

    def has_active_run(self, conversation_id: str) -> bool:
        """True while an analysis started over a WS is still executing."""
        return self._active_runs.get(conversation_id, 0) > 0
