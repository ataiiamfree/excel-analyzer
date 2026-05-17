"""OpenAI-compatible LLM client for DeepSeek."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 调用失败。"""


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120)
        return self._client

    async def call(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.1,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

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
        content = message.get("content") or ""
        if not content.strip() and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return content

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
