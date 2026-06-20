"""FastAPI dependency factories and process-local registries."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from app.config import Config
from app.session import Session
from app.api.persistence.store import Store


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()


@lru_cache(maxsize=1)
def get_store() -> Store:
    return Store(get_config().api_db_path)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, conversation: dict[str, Any]) -> Session:
        conversation_id = conversation["id"]
        session = self._sessions.get(conversation_id)
        if session is not None:
            return session
        file_path = conversation.get("local_file_path")
        if not file_path:
            raise ValueError("会话缺少可分析的文件路径")
        session = Session(session_id=conversation_id, file_path=file_path)
        self._sessions[conversation_id] = session
        return session

    def replace_file(self, conversation_id: str, file_path: str) -> Session:
        session = Session(session_id=conversation_id, file_path=file_path)
        self._sessions[conversation_id] = session
        return session


class RunRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._states: dict[str, dict[str, Any]] = {}

    def put(self, run_id: str, task: asyncio.Task, state: dict[str, Any]) -> None:
        self._tasks[run_id] = task
        self._states[run_id] = state

    def update(self, run_id: str, **state: Any) -> None:
        current = self._states.setdefault(run_id, {})
        current.update(state)

    def get_state(self, run_id: str) -> dict[str, Any] | None:
        return self._states.get(run_id)

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        self.update(run_id, status="cancelled")
        return True


@lru_cache(maxsize=1)
def get_session_registry() -> SessionRegistry:
    return SessionRegistry()


@lru_cache(maxsize=1)
def get_run_registry() -> RunRegistry:
    return RunRegistry()
