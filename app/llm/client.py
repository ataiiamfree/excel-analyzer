"""OpenAI-compatible LLM client for DeepSeek."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用失败。"""


@dataclass(frozen=True)
class LLMStreamEvent:
    kind: Literal["content", "reasoning"]
    text: str


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        thinking: bool = False,
        effort: str = "",
        timeout: float = 180,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.thinking = thinking
        self.effort = effort
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self.reasoning_callback: Callable[[str], Awaitable[None]] | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(self.timeout, connect=30)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def call(
        self,
        prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.1,
        thinking: bool | None = None,
    ) -> str:
        if self.reasoning_callback:
            chunks: list[str] = []
            async for event in self.stream_events(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking=thinking,
            ):
                if event.kind == "content":
                    chunks.append(event.text)
            content = "".join(chunks)
            if not content.strip():
                raise LLMError("LLM 流式响应为空")
            logger.info("LLM 流式 call 响应: %d chars", len(content))
            return content

        payload = self._build_payload(prompt, max_tokens, temperature, thinking, stream=False)
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info("LLM 请求: model=%s, prompt=%d chars, max_tokens=%d",
                    self.model, len(prompt), max_tokens)
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM API 返回 {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.RequestError as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"LLM 响应非 JSON: {response.text[:300]}") from exc

        choices = data.get("choices")
        if not choices:
            raise LLMError(f"LLM 响应缺少 choices: {data}")
        message = choices[0].get("message", {})
        reasoning_content = message.get("reasoning_content") or ""
        if reasoning_content and self.reasoning_callback:
            await self.reasoning_callback(reasoning_content)
        content = message.get("content") or ""
        if not content.strip() and message.get("reasoning_content"):
            logger.warning("LLM response only contained reasoning_content; ignoring it as executable output")
        if not content.strip():
            finish_reason = choices[0].get("finish_reason")
            raise LLMError(f"LLM 响应为空: finish_reason={finish_reason}")
        logger.info("LLM 响应: %d chars", len(content))
        return content

    async def stream(
        self,
        prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.1,
        thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion content chunks from an OpenAI-compatible API."""
        async for event in self.stream_events(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking=thinking,
        ):
            if event.kind == "content":
                yield event.text

    async def stream_events(
        self,
        prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.1,
        thinking: bool | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Stream content and reasoning events from an OpenAI-compatible API."""
        payload = self._build_payload(prompt, max_tokens, temperature, thinking, stream=True)
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info("LLM 流式请求: model=%s, prompt=%d chars, max_tokens=%d",
                    self.model, len(prompt), max_tokens)
        client = await self._get_client()
        streamed_chars = 0
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise LLMError(f"LLM API 返回 {response.status_code}: {body[:500]}")

                async for line in response.aiter_lines():
                    event = self._parse_stream_event(line)
                    if event is None:
                        continue
                    if event == "[DONE]":
                        break
                    streamed_chars += len(event.text)
                    if event.kind == "reasoning" and self.reasoning_callback:
                        await self.reasoning_callback(event.text)
                    yield event
        except LLMError:
            raise
        except httpx.RequestError as exc:
            raise LLMError(f"LLM 流式请求失败: {exc}") from exc

        if streamed_chars <= 0:
            raise LLMError("LLM 流式响应为空")
        logger.info("LLM 流式响应完成: %d chars", streamed_chars)

    def _parse_stream_line(self, line: str) -> str | None:
        event = self._parse_stream_event(line)
        if event == "[DONE]":
            return "[DONE]"
        if event is None or event.kind != "content":
            return None
        return event.text

    def _parse_stream_event(self, line: str) -> LLMStreamEvent | str | None:
        text = (line or "").strip()
        if not text or text.startswith(":"):
            return None
        if text.startswith("data:"):
            text = text[5:].strip()
        if text == "[DONE]":
            return "[DONE]"

        try:
            data = json.loads(text)
        except ValueError as exc:
            raise LLMError(f"LLM 流式响应非 JSON: {text[:300]}") from exc

        choices = data.get("choices") or []
        if not choices:
            return None
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        reasoning = delta.get("reasoning_content") or message.get("reasoning_content")
        if reasoning:
            return LLMStreamEvent(kind="reasoning", text=reasoning)
        content = delta.get("content") or message.get("content")
        if content:
            return LLMStreamEvent(kind="content", text=content)
        return None

    def _build_payload(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        thinking: bool | None,
        *,
        stream: bool,
    ) -> dict:
        use_thinking = self.thinking if thinking is None else thinking
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "thinking": {"type": "enabled" if use_thinking else "disabled"},
        }
        if stream:
            payload["stream"] = True
        if self.effort and use_thinking:
            payload["reasoning_effort"] = self.effort
        return payload

    def count_tokens(self, text: str) -> int:
        # 中文字符约 1-2 token，英文约 1 token / 4 chars
        # 对中文使用更保守的估算
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
        rest = len(text) - cjk
        return max(1, cjk + rest // 4)

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
