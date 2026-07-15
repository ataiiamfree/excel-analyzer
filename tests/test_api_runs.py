"""Tests for the /api/runs headless endpoints."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.api import deps
from app.api.routers import runs


class _StubConfig:
    def __init__(self, workspace_dir):
        self.workspace_dir = str(workspace_dir)
        self.max_file_size_mb = 100


def test_save_ephemeral_upload_cleans_workspace_on_validation_failure(
    tmp_path, monkeypatch
):
    """Rejected uploads must not leave orphaned workspace directories.

    Regression guard: `Workspace(...)` eagerly mkdirs its skeleton; a burst of
    413/415/422 responses would otherwise pile up empty run_* directories.
    """
    config = _StubConfig(tmp_path / "workspaces")

    def raise_validation(*args, **kwargs):
        raise HTTPException(status_code=415, detail="fake reject")

    monkeypatch.setattr(runs, "save_validated_excel", raise_validation)

    upload = UploadFile(filename="bad.xls", file=BytesIO(b"junk"))
    with pytest.raises(HTTPException) as exc:
        runs.save_ephemeral_upload(upload, config)
    assert exc.value.status_code == 415

    workspace_root = tmp_path / "workspaces"
    # Whatever run_* directory was created must have been wiped again.
    assert not any(workspace_root.iterdir()), (
        f"orphaned workspace children: {list(workspace_root.iterdir())}"
    )


def test_run_registry_cancel_ignores_completed_tasks():
    """Cancelling a task that already finished must not fabricate a cancelled
    state — the release doc says GET/DELETE reflect real lifecycle."""

    registry = deps.RunRegistry()

    async def scenario():
        async def done_task():
            return "ok"

        task = asyncio.create_task(done_task())
        await task  # let it complete
        registry.put(
            "run_done",
            task,
            {"status": "done"},
        )
        assert registry.cancel("run_done") is False
        # State must be untouched — cancel() lied before this fix.
        assert registry.get_state("run_done") == {"status": "done"}

    asyncio.run(scenario())


def test_run_registry_cancel_running_task_marks_state():
    registry = deps.RunRegistry()

    async def scenario():
        async def long_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_task())
        registry.put("run_alive", task, {"status": "running"})
        assert registry.cancel("run_alive") is True
        # Task cancellation propagates on the next await; give the loop a tick.
        await asyncio.sleep(0)
        assert task.cancelled()
        assert registry.get_state("run_alive")["status"] == "cancelled"

    asyncio.run(scenario())


def test_run_registry_missing_run_returns_false():
    registry = deps.RunRegistry()
    assert registry.cancel("nope") is False


def test_run_semaphore_serialises_concurrent_runs(monkeypatch):
    """Two runs launched simultaneously must not both hold the semaphore.

    Regression guard: `MAX_CONCURRENT_TASKS` used to be config-only with no
    enforcement; unbounded concurrency was documented but not implemented.
    """

    from app.api.ws import runner

    runner._reset_run_semaphore_for_tests()

    class _Cfg:
        max_concurrent_tasks = 1

    concurrent = {"peak": 0, "current": 0}

    async def scenario():
        async def body():
            async with runner._get_run_semaphore(_Cfg()):
                concurrent["current"] += 1
                concurrent["peak"] = max(concurrent["peak"], concurrent["current"])
                await asyncio.sleep(0.05)
                concurrent["current"] -= 1

        await asyncio.gather(*(body() for _ in range(4)))

    try:
        asyncio.run(scenario())
    finally:
        runner._reset_run_semaphore_for_tests()

    assert concurrent["peak"] == 1, (
        f"semaphore did not serialise runs; peak concurrency = {concurrent['peak']}"
    )


def test_run_semaphore_respects_higher_limit():
    from app.api.ws import runner

    runner._reset_run_semaphore_for_tests()

    class _Cfg:
        max_concurrent_tasks = 3

    concurrent = {"peak": 0, "current": 0}

    async def scenario():
        async def body():
            async with runner._get_run_semaphore(_Cfg()):
                concurrent["current"] += 1
                concurrent["peak"] = max(concurrent["peak"], concurrent["current"])
                await asyncio.sleep(0.03)
                concurrent["current"] -= 1

        await asyncio.gather(*(body() for _ in range(5)))

    try:
        asyncio.run(scenario())
    finally:
        runner._reset_run_semaphore_for_tests()

    assert concurrent["peak"] == 3, (
        f"expected peak concurrency 3, got {concurrent['peak']}"
    )
