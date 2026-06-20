import json

from app.llm.client import LLMClient


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
