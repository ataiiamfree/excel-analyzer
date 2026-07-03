"""Application configuration.

The project is currently a single-user/internal tool. Secrets still come from
environment variables so they do not leak into code, docs, or task artifacts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass
class Config:
    llm_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    llm_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    llm_thinking: bool = field(
        default_factory=lambda: os.getenv("DEEPSEEK_THINKING", "true").lower() in {"1", "true", "yes", "on"}
    )
    llm_reasoning_effort: str = field(default_factory=lambda: os.getenv("DEEPSEEK_REASONING_EFFORT", ""))

    budget_preset: str = field(default_factory=lambda: os.getenv("BUDGET_PRESET", "deepseek"))

    workspace_dir: str = field(default_factory=lambda: os.getenv("WORKSPACE_DIR", "./workspace"))
    web_dist_dir: str = field(default_factory=lambda: os.getenv("WEB_DIST_DIR", "./web/dist"))
    api_db_path: str = field(default_factory=lambda: os.getenv("API_DB_PATH", "./workspace/chat_excel.sqlite3"))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"))
    run_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("RUN_TIMEOUT_SECONDS", "300")))
    ephemeral_ttl_hours: int = field(default_factory=lambda: int(os.getenv("EPHEMERAL_TTL_HOURS", "24")))
    llm_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "180")))
    sandbox_timeout: int = field(default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT", "60")))
    sandbox_memory_mb: int = field(default_factory=lambda: int(os.getenv("SANDBOX_MEMORY_MB", "1024")))
    max_stdout_chars: int = field(default_factory=lambda: int(os.getenv("MAX_STDOUT_CHARS", "20000")))
    max_repair_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_REPAIR_ATTEMPTS", "2")))
    max_semantic_repair_attempts: int = field(
        default_factory=lambda: int(os.getenv("MAX_SEMANTIC_REPAIR_ATTEMPTS", "1"))
    )
    max_file_size_mb: int = field(default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_MB", "100")))
    max_concurrent_tasks: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_TASKS", "1")))

    pi_command: str = field(default_factory=lambda: os.getenv("PI_COMMAND", "pi"))
    pi_args: str = field(default_factory=lambda: os.getenv("PI_ARGS", "--mode rpc --no-session"))
    pi_cwd: str = field(default_factory=lambda: os.getenv("PI_CWD", "."))
    pi_provider: str = field(default_factory=lambda: os.getenv("PI_PROVIDER", ""))
    pi_model: str = field(default_factory=lambda: os.getenv("PI_MODEL", ""))
    pi_stream_limit_bytes: int = field(
        default_factory=lambda: int(os.getenv("PI_STREAM_LIMIT_BYTES", str(16 * 1024 * 1024)))
    )
