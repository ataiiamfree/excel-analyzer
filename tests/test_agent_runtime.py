import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agent.runtime import (
    PiRpcTransport,
    PiRuntimeError,
    PiSidecarRuntimeAdapter,
    RuntimeRequest,
    build_agent_runtime,
)
from app.config import Config


class FakeTransport:
    def __init__(self, events=None, result=None, exc=None):
        self.events = events or []
        self.result = result or {}
        self.exc = exc
        self.payload = None

    async def run(self, payload, event_handler):
        self.payload = payload
        if self.exc:
            raise self.exc
        for event in self.events:
            await event_handler(event)
        return self.result


class FakeStdout:
    def __init__(self, events):
        self.lines = [
            (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
            for event in events
        ]

    async def readline(self):
        if not self.lines:
            return b""
        return self.lines.pop(0)


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, events):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(events)
        self.stderr = FakeStdout([])
        self.returncode = None
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    async def wait(self):
        self.returncode = 0
        return 0


def test_pi_sidecar_maps_events_to_callbacks(tmp_path):
    events = [
        {"type": "agent_start"},
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "thinking_delta", "delta": "思考"},
        },
        {
            "type": "tool_execution_start",
            "toolName": "bash",
            "args": {"command": "python -m app.agent.pi_tool_service"},
        },
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "报告"},
        },
        {"type": "agent_end", "messages": []},
    ]
    callbacks = {"plans": [], "starts": [], "ends": [], "reports": [], "reasoning": []}

    async def on_plan_ready(plan):
        callbacks["plans"].append(plan)

    async def on_step_start(step, index, total):
        callbacks["starts"].append((step, index, total))

    async def on_step_end(step, result):
        callbacks["ends"].append((step, result))

    async def on_report_token(token):
        callbacks["reports"].append(token)

    async def on_reasoning_token(token):
        callbacks["reasoning"].append(token)

    config = Config(workspace_dir=str(tmp_path))
    adapter = PiSidecarRuntimeAdapter(
        config=config,
        transport=FakeTransport(events=events, result={"files": ["output/a.csv"]}),
    )
    session = SimpleNamespace(session_id="s1", file_path="/tmp/a.xlsx", tasks=[])

    result = asyncio.run(
        adapter.run(
            RuntimeRequest(
                query="分析",
                session=session,
                callbacks={
                    "on_plan_ready": on_plan_ready,
                    "on_step_start": on_step_start,
                    "on_step_end": on_step_end,
                    "on_report_token": on_report_token,
                    "on_reasoning_token": on_reasoning_token,
                },
            )
        )
    )

    assert result.report == "报告"
    assert result.files == ["output/a.csv"]
    assert callbacks["plans"][0].steps[0].tool == "pi"
    assert callbacks["starts"][0][0].id == "pi-runtime"
    assert callbacks["ends"][0][1].success
    assert "思考" in "".join(callbacks["reasoning"])
    assert "python -m app.agent.pi_tool_service" in adapter.transport.payload["prompt"]
    assert "spreadsheet.ingest_workbook" in adapter.transport.payload["prompt"]
    assert "<<FINAL_REPORT>>" in adapter.transport.payload["prompt"]


def test_pi_sidecar_keeps_prefinal_text_out_of_report(tmp_path):
    events = [
        {"type": "agent_start"},
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "我先分析执行计划。"},
        },
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "<<FINAL_REPORT>>总预算 544.20 万元。"},
        },
        {"type": "agent_end", "messages": []},
    ]
    reports = []
    reasoning = []

    async def on_report_token(token):
        reports.append(token)

    async def on_reasoning_token(token):
        reasoning.append(token)

    adapter = PiSidecarRuntimeAdapter(
        config=Config(workspace_dir=str(tmp_path)),
        transport=FakeTransport(events=events),
    )
    session = SimpleNamespace(session_id="s1", file_path="/tmp/a.xlsx", tasks=[])

    result = asyncio.run(
        adapter.run(
            RuntimeRequest(
                query="分析预算",
                session=session,
                callbacks={
                    "on_report_token": on_report_token,
                    "on_reasoning_token": on_reasoning_token,
                },
            )
        )
    )

    assert result.report == "总预算 544.20 万元。"
    assert "".join(reports) == "总预算 544.20 万元。"
    assert "我先分析执行计划" in "".join(reasoning)
    assert "我先分析执行计划" not in result.report


def test_build_agent_runtime_returns_pi_sidecar(tmp_path):
    config = Config(workspace_dir=str(tmp_path))

    runtime = build_agent_runtime(
        config,
        pi_transport=FakeTransport(),
    )

    assert isinstance(runtime, PiSidecarRuntimeAdapter)
    assert runtime.name == "pi-sidecar"


def test_build_agent_runtime_does_not_fallback_when_pi_fails(tmp_path):
    config = Config(workspace_dir=str(tmp_path))
    runtime = build_agent_runtime(
        config,
        pi_transport=FakeTransport(exc=PiRuntimeError("boom")),
    )

    with pytest.raises(PiRuntimeError, match="boom"):
        asyncio.run(
            runtime.run(
                RuntimeRequest(
                    query="继续分析",
                    session=SimpleNamespace(session_id="s1", file_path="/tmp/a.xlsx", tasks=[]),
                )
            )
        )


def test_pi_rpc_transport_sends_prompt_and_reads_agent_events():
    process_holder = {}
    events = [
        {"id": "prompt-s1", "type": "response", "command": "prompt", "success": True},
        {"type": "agent_start"},
        {"type": "agent_end", "messages": []},
    ]

    async def process_factory(command, cwd=None, env=None):
        process = FakeProcess(events)
        process_holder["process"] = process
        process_holder["command"] = command
        return process

    seen = []

    async def on_event(event):
        seen.append(event)

    transport = PiRpcTransport(
        command=["pi", "--mode", "rpc", "--no-session"],
        process_factory=process_factory,
    )

    result = asyncio.run(transport.run({"session_id": "s1", "prompt": "你好"}, on_event))

    written = process_holder["process"].stdin.writes[0].decode("utf-8")
    assert json.loads(written)["message"] == "你好"
    assert process_holder["command"] == ["pi", "--mode", "rpc", "--no-session"]
    assert [event["type"] for event in seen] == ["agent_start", "agent_end"]
    assert result["event_count"] == 2
