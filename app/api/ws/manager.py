"""Minimal connection manager for conversation WebSockets."""

from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

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
