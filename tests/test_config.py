from app.config import Config


def test_deepseek_defaults_are_aligned():
    config = Config()

    assert config.llm_base_url == "https://api.deepseek.com"
    assert config.llm_model == "deepseek-v4-pro"
    assert config.budget_preset == "deepseek"
