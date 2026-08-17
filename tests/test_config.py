"""风格档案与配置测试。"""

import pytest
from pydantic import ValidationError

from config import STYLE_PROFILES, Config, get_style_prompt

REQUIRED_KEYS = {"name", "syntax", "sentence_length", "vocabulary", "narrative_techniques", "pacing", "examples"}


def test_style_profiles_complete():
    """四种内置风格档案字段完整(六维 + 示例)。"""
    assert set(STYLE_PROFILES) == {"jin_yong", "gu_long", "murakami", "yu_hua"}
    for key, profile in STYLE_PROFILES.items():
        missing = REQUIRED_KEYS - set(profile)
        assert not missing, f"{key} 缺少字段: {missing}"
        assert profile["examples"], f"{key} 示例为空"
        assert profile["syntax"] and profile["vocabulary"]


def test_get_style_prompt_known():
    text = get_style_prompt("gu_long")
    assert "古龙风格" in text
    assert "短句为主" in text
    assert "天涯远不远" in text


def test_get_style_prompt_unknown_falls_back():
    text = get_style_prompt("no_such_style")
    assert "金庸风格" in text  # 回退默认
    assert "no_such_style" in text  # 提示未知风格


def test_config_defaults():
    cfg = Config()
    assert cfg.llm_provider in {"openai", "anthropic"}
    assert cfg.total_chapters >= 1
    assert 0 <= cfg.temperature <= 2


def test_config_rejects_unknown_llm_provider():
    with pytest.raises(ValidationError):
        Config(llm_provider="unknown")


def test_config_has_persistent_checkpoint_path(tmp_path):
    path = tmp_path / "checkpoints.db"
    cfg = Config(checkpoint_db_path=str(path))
    assert cfg.checkpoint_db_path == str(path)
