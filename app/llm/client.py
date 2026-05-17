"""OpenAI-compatible LLM client for DeepSeek."""

from __future__ import annotations

import httpx


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

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

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        if not content.strip() and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return content

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 3)
