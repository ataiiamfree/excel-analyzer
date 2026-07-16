"""Unit tests for the small dep-injected registries in `app.api.deps`."""

from __future__ import annotations

from app.api.deps import SessionRegistry


def test_session_registry_delete_removes_cached_session():
    registry = SessionRegistry()
    registry.replace_file("conv-1", "/tmp/one.xlsx")
    registry.replace_file("conv-2", "/tmp/two.xlsx")

    registry.delete("conv-1")

    assert "conv-1" not in registry._sessions
    # Untouched sibling is not disturbed.
    assert "conv-2" in registry._sessions


def test_session_registry_delete_is_noop_on_missing_id():
    """Regression guard: deleting an already-gone id must not raise."""
    registry = SessionRegistry()
    # No exception, no state — long-lived processes call delete unconditionally
    # after workspace rmtree.
    registry.delete("never-existed")
