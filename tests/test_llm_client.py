import asyncio
import json

import pytest

from app.llm.client import LLMClient, LLMError


def _stream_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}"


class FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self.lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aread(self):
        return b""


class FakeAsyncClient:
    is_closed = False

    def __init__(self, lines: list[str]):
        self.lines = lines

    def stream(self, *args, **kwargs):
        return FakeStreamResponse(self.lines)


def test_parse_stream_line_extracts_delta_content():
    client = LLMClient(base_url="https://example.test", model="test")
    payload = {"choices": [{"delta": {"content": "你好"}}]}

    assert client._parse_stream_line(f"data: {json.dumps(payload, ensure_ascii=False)}") == "你好"


def test_parse_stream_event_extracts_reasoning_content():
    client = LLMClient(base_url="https://example.test", model="test")
    payload = {"choices": [{"delta": {"reasoning_content": "先检查字段"}}]}

    event = client._parse_stream_event(f"data: {json.dumps(payload, ensure_ascii=False)}")

    assert event is not None
    assert event.kind == "reasoning"
    assert event.text == "先检查字段"
    assert client._parse_stream_line(f"data: {json.dumps(payload, ensure_ascii=False)}") is None


def test_parse_stream_line_detects_done_marker():
    client = LLMClient(base_url="https://example.test", model="test")

    assert client._parse_stream_line("data: [DONE]") == "[DONE]"


def test_parse_stream_line_ignores_empty_and_comment_lines():
    client = LLMClient(base_url="https://example.test", model="test")

    assert client._parse_stream_line("") is None
    assert client._parse_stream_line(": keep-alive") is None


def test_build_payload_disables_thinking_explicitly():
    client = LLMClient(base_url="https://example.test", model="test", thinking=True, effort="low")

    payload = client._build_payload("prompt", 100, 0.1, thinking=False, stream=True)

    assert payload["stream"] is True
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_stream_events_routes_reasoning_without_mixing_content():
    client = LLMClient(base_url="https://example.test", model="test")
    client._client = FakeAsyncClient([
        _stream_data({"choices": [{"delta": {"reasoning_content": "先判断口径"}}]}),
        _stream_data({"choices": [{"delta": {"content": "最终答案"}}]}),
        "data: [DONE]",
    ])
    reasoning_chunks: list[str] = []

    async def on_reasoning(text: str):
        reasoning_chunks.append(text)

    async def collect_events():
        return [
            event
            async for event in client.stream_events("prompt", reasoning_callback=on_reasoning)
        ]

    events = asyncio.run(collect_events())

    assert reasoning_chunks == ["先判断口径"]
    assert [event.kind for event in events] == ["reasoning", "content"]
    assert events[-1].text == "最终答案"


def test_stream_events_rejects_reasoning_only_response():
    client = LLMClient(base_url="https://example.test", model="test")
    client._client = FakeAsyncClient([
        _stream_data({"choices": [{"delta": {"reasoning_content": "只有思考"}}]}),
        "data: [DONE]",
    ])

    async def consume_events():
        async for _ in client.stream_events("prompt"):
            pass

    with pytest.raises(LLMError, match="缺少 content"):
        asyncio.run(consume_events())
