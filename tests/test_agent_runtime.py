import asyncio
from types import SimpleNamespace

from app.agent.runtime import OrchestratorRuntimeAdapter, PiSidecarRuntimeAdapter, RuntimeRequest


class FakeOrchestrator:
    async def run(self, **kwargs):
        return SimpleNamespace(report=f"ok:{kwargs['query']}", files=[])


def test_orchestrator_runtime_adapter_delegates_run():
    adapter = OrchestratorRuntimeAdapter(FakeOrchestrator())
    request = RuntimeRequest(query="分析", session=SimpleNamespace())

    result = asyncio.run(adapter.run(request))

    assert result.report == "ok:分析"


def test_pi_sidecar_runtime_adapter_uses_transport_payload():
    seen = {}

    async def transport(payload):
        seen.update(payload)
        return {"status": "ok", "answer": payload["query"]}

    adapter = PiSidecarRuntimeAdapter(transport)
    session = SimpleNamespace(session_id="s1", file_path="/tmp/a.xlsx", tasks=["t1"])

    result = asyncio.run(adapter.run(RuntimeRequest(query="解释产物", session=session)))

    assert result["answer"] == "解释产物"
    assert seen["session_id"] == "s1"
    assert seen["prior_tasks"] == ["t1"]
