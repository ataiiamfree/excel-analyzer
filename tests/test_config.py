import os
from unittest.mock import patch

from app.config import Config


def test_deepseek_defaults_are_aligned():
    # 清除环境变量，确保测试的是真正的默认值
    env_keys = [
        "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY",
        "DEEPSEEK_THINKING", "DEEPSEEK_REASONING_EFFORT",
        "BUDGET_PRESET", "WORKSPACE_DIR", "LLM_TIMEOUT_SECONDS", "SANDBOX_TIMEOUT",
        "SANDBOX_MEMORY_MB", "MAX_STDOUT_CHARS", "MAX_REPAIR_ATTEMPTS",
        "MAX_FILE_SIZE_MB", "MAX_CONCURRENT_TASKS",
        "AGENT_RUNTIME", "AGENT_RUNTIME_FALLBACK", "PI_COMMAND", "PI_ARGS",
        "PI_CWD", "PI_PROVIDER", "PI_MODEL",
    ]
    clean_env = {k: v for k, v in os.environ.items() if k not in env_keys}
    with patch.dict(os.environ, clean_env, clear=True):
        config = Config()

    assert config.llm_base_url == "https://api.deepseek.com"
    assert config.llm_model == "deepseek-v4-pro"
    assert config.llm_thinking is True
    assert config.llm_reasoning_effort == ""
    assert config.llm_timeout_seconds == 180
    assert config.budget_preset == "deepseek"
    assert config.agent_runtime == "pi"
    assert config.agent_runtime_fallback is True
    assert config.pi_command == "pi"
    assert config.pi_args == "--mode rpc --no-session"


def test_env_override():
    overrides = {
        "DEEPSEEK_BASE_URL": "https://custom.api",
        "DEEPSEEK_MODEL": "custom-model",
        "DEEPSEEK_THINKING": "false",
        "DEEPSEEK_REASONING_EFFORT": "low",
        "BUDGET_PRESET": "generous",
        "LLM_TIMEOUT_SECONDS": "45",
        "SANDBOX_TIMEOUT": "120",
        "AGENT_RUNTIME": "orchestrator",
        "AGENT_RUNTIME_FALLBACK": "false",
        "PI_COMMAND": "custom-pi",
        "PI_ARGS": "--mode rpc --no-session --no-color",
        "PI_PROVIDER": "openai",
        "PI_MODEL": "openai/gpt-5",
    }
    with patch.dict(os.environ, overrides):
        config = Config()

    assert config.llm_base_url == "https://custom.api"
    assert config.llm_model == "custom-model"
    assert config.llm_thinking is False
    assert config.llm_reasoning_effort == "low"
    assert config.budget_preset == "generous"
    assert config.llm_timeout_seconds == 45
    assert config.sandbox_timeout == 120
    assert config.agent_runtime == "orchestrator"
    assert config.agent_runtime_fallback is False
    assert config.pi_command == "custom-pi"
    assert config.pi_args == "--mode rpc --no-session --no-color"
    assert config.pi_provider == "openai"
    assert config.pi_model == "openai/gpt-5"
