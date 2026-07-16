"""Unit tests for the WebSocket ConnectionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.api.ws.manager import ConnectionManager


def test_has_active_reflects_registered_connections():
    manager = ConnectionManager()

    assert manager.has_active("conv-1") is False

    fake_ws = AsyncMock()
    # `connect` awaits `websocket.accept`; we sidestep it and populate the
    # internal map directly since this test only cares about has_active.
    manager._connections["conv-1"].add(fake_ws)
    assert manager.has_active("conv-1") is True

    manager.disconnect("conv-1", fake_ws)
    assert manager.has_active("conv-1") is False


def test_has_active_is_isolated_across_conversations():
    manager = ConnectionManager()
    fake_ws = AsyncMock()
    manager._connections["conv-1"].add(fake_ws)

    assert manager.has_active("conv-1") is True
    assert manager.has_active("conv-2") is False
