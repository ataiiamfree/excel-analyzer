import json

from app.llm.client import LLMClient


def test_parse_stream_line_extracts_delta_content():
    client = LLMClient(base_url="https://example.test", model="test")
    payload = {"choices": [{"delta": {"content": "你好"}}]}

    assert client._parse_stream_line(f"data: {json.dumps(payload, ensure_ascii=False)}") == "你好"


def test_parse_stream_line_detects_done_marker():
    client = LLMClient(base_url="https://example.test", model="test")

    assert client._parse_stream_line("data: [DONE]") == "[DONE]"


def test_parse_stream_line_ignores_empty_and_comment_lines():
    client = LLMClient(base_url="https://example.test", model="test")

    assert client._parse_stream_line("") is None
    assert client._parse_stream_line(": keep-alive") is None
