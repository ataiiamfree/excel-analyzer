"""Unit tests for the WebSocket ConnectionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.api.ws.manager import ConnectionManager


def test_has_connections_reflects_registered_connections():
    manager = ConnectionManager()

    assert manager.has_connections("conv-1") is False

    fake_ws = AsyncMock()
    # `connect` awaits `websocket.accept`; we sidestep it and populate the
    # internal map directly since this test only cares about has_connections.
    manager._connections["conv-1"].add(fake_ws)
    assert manager.has_connections("conv-1") is True

    manager.disconnect("conv-1", fake_ws)
    assert manager.has_connections("conv-1") is False


def test_has_connections_is_isolated_across_conversations():
    manager = ConnectionManager()
    fake_ws = AsyncMock()
    manager._connections["conv-1"].add(fake_ws)

    assert manager.has_connections("conv-1") is True
    assert manager.has_connections("conv-2") is False


def test_connection_alone_is_not_an_active_run():
    """P1-6 fix: an idle open page (WS connected, no run) must not read as
    "analysis executing" — that conflation blocked deleting idle conversations."""
    manager = ConnectionManager()
    fake_ws = AsyncMock()
    manager._connections["conv-1"].add(fake_ws)

    assert manager.has_connections("conv-1") is True
    assert manager.has_active_run("conv-1") is False


def test_begin_end_run_tracks_active_run():
    manager = ConnectionManager()

    assert manager.has_active_run("conv-1") is False
    manager.begin_run("conv-1")
    assert manager.has_active_run("conv-1") is True
    manager.end_run("conv-1")
    assert manager.has_active_run("conv-1") is False


def test_end_run_without_begin_is_a_noop():
    manager = ConnectionManager()
    manager.end_run("conv-1")
    assert manager.has_active_run("conv-1") is False

    # A later begin still counts correctly (no negative underflow).
    manager.begin_run("conv-1")
    assert manager.has_active_run("conv-1") is True


def test_active_runs_are_isolated_across_conversations():
    manager = ConnectionManager()
    manager.begin_run("conv-1")

    assert manager.has_active_run("conv-1") is True
    assert manager.has_active_run("conv-2") is False
