"""Thin HTTP client for ChatExcel headless eval runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import httpx


@dataclass
class ChatExcelClient:
    base_url: str = "http://127.0.0.1:8000"

    def run(
        self,
        *,
        file: str | Path,
        query: str,
        timeout: float = 300,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one Excel question through the deployed HTTP API."""
        path = Path(file)
        with path.open("rb") as fh:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/runs",
                files={"file": (path.name, fh, self._mime(path))},
                data={
                    "query": query,
                    "params": "{}" if params is None else json.dumps(params, ensure_ascii=False),
                    "ephemeral": "true",
                },
                timeout=timeout,
            )
        response.raise_for_status()
        return response.json()

    def download_artifact(self, artifact_url: str, target: str | Path, timeout: float = 120) -> Path:
        target_path = Path(target)
        response = httpx.get(f"{self.base_url.rstrip('/')}{artifact_url}", timeout=timeout)
        response.raise_for_status()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(response.content)
        return target_path

    def _mime(self, path: Path) -> str:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/octet-stream"
