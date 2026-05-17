"""Application configuration.

The project is currently a single-user/internal tool. Secrets still come from
environment variables so they do not leak into code, docs, or task artifacts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    llm_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    llm_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))

    budget_preset: str = field(default_factory=lambda: os.getenv("BUDGET_PRESET", "deepseek"))

    workspace_dir: str = field(default_factory=lambda: os.getenv("WORKSPACE_DIR", "./workspace"))
    sandbox_timeout: int = field(default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT", "60")))
    sandbox_memory_mb: int = field(default_factory=lambda: int(os.getenv("SANDBOX_MEMORY_MB", "1024")))
    max_stdout_chars: int = field(default_factory=lambda: int(os.getenv("MAX_STDOUT_CHARS", "20000")))
    max_repair_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_REPAIR_ATTEMPTS", "2")))
    max_file_size_mb: int = field(default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_MB", "100")))
    max_concurrent_tasks: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_TASKS", "1")))
