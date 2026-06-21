"""Agent runtime adapters.

The API layer talks to this module instead of depending directly on a specific
orchestrator implementation. The default adapter wraps the existing Python
orchestrator; the Pi sidecar adapter is intentionally transport-based so it can
be tested without installing Pi in the Python environment.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


RuntimeTransport = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class RuntimeRequest:
    query: str
    session: Any
    callbacks: dict[str, Any] = field(default_factory=dict)


class AgentRuntimeAdapter:
    name = "base"

    async def run(self, request: RuntimeRequest) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


class OrchestratorRuntimeAdapter(AgentRuntimeAdapter):
    name = "orchestrator"

    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator

    async def run(self, request: RuntimeRequest) -> Any:
        return await self.orchestrator.run(
            query=request.query,
            session=request.session,
            **request.callbacks,
        )


class PiSidecarRuntimeAdapter(AgentRuntimeAdapter):
    """Experimental adapter for a Pi/RPC sidecar.

    The adapter exchanges plain JSON-compatible payloads with an injected
    transport. A production transport can call Pi RPC; tests can provide a fake
    async callable.
    """

    name = "pi-sidecar"

    def __init__(self, transport: RuntimeTransport):
        self.transport = transport

    async def run(self, request: RuntimeRequest) -> dict[str, Any]:
        payload = {
            "query": request.query,
            "session_id": getattr(request.session, "session_id", None),
            "file_path": getattr(request.session, "file_path", None),
            "prior_tasks": list(getattr(request.session, "tasks", [])),
        }
        return await self.transport(payload)
