"""运行时设置(LLM provider/model 等):默认值 < data/config.json < 环境变量。

可在 Web 设置页热改并持久化;部署级配置见 core.config.DeploySettings。
"""

import contextlib
import json
import os
from pathlib import Path
from typing import Any

PROVIDER_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "mock": "mock",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "provider": "openai",  # openai | anthropic | mock(离线演示)
    "model": "",
    "base_url": "",
    "api_key": "",
    "temperature": 0.8,
    "chapter_words": 2500,
}

ENV_KEYS = {
    "provider": "NOVEL_AGENT_PROVIDER",
    "model": "NOVEL_AGENT_MODEL",
    "base_url": "NOVEL_AGENT_BASE_URL",
    "api_key": "NOVEL_AGENT_API_KEY",
    "temperature": "NOVEL_AGENT_TEMPERATURE",
    "chapter_words": "NOVEL_AGENT_CHAPTER_WORDS",
}

PERSIST_FIELDS = ["provider", "model", "base_url", "api_key", "temperature", "chapter_words"]

# API Key 脱敏展示前缀;保存时收到以该前缀开头的值视为「未修改」
MASK_PREFIX = "***"


def mask_secret(value: str) -> str:
    """脱敏 API Key:保留前 3 后 4 位,短值整体打码。"""
    if not value:
        return ""
    if len(value) <= 8:
        return MASK_PREFIX + "****"
    return f"{MASK_PREFIX}{value[:3]}…{value[-4:]}"


class RuntimeSettingsStore:
    """data/config.json 的读写,注入具体文件路径以便测试与多环境部署。"""

    def __init__(self, config_file: Path):
        self.config_file = config_file

    def _file_settings(self) -> dict[str, Any]:
        try:
            if self.config_file.exists():
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                return {k: v for k, v in data.items() if k in PERSIST_FIELDS}
        except Exception:
            pass
        return {}

    def load(self) -> dict[str, Any]:
        s: dict[str, Any] = dict(DEFAULT_SETTINGS)
        s.update(self._file_settings())
        for key, env in ENV_KEYS.items():
            val = os.environ.get(env)
            if val not in (None, ""):
                if key == "temperature":
                    with contextlib.suppress(ValueError):
                        s[key] = float(val)
                elif key == "chapter_words":
                    with contextlib.suppress(ValueError):
                        s[key] = int(val)
                else:
                    s[key] = val
        # api_key 为空时回退到各 provider 的通用环境变量
        if not s["api_key"]:
            fallback = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(s["provider"])
            if fallback:
                s["api_key"] = os.environ.get(fallback, "")
        if not s["model"]:
            s["model"] = PROVIDER_DEFAULT_MODEL.get(s["provider"], "")
        return s

    def load_masked(self) -> dict[str, Any]:
        """对外(设置页/API)安全视图:api_key 脱敏。"""
        s = self.load()
        s["api_key_set"] = bool(s.get("api_key"))
        s["api_key"] = mask_secret(s.get("api_key", ""))
        return s

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        """合并保存。收到脱敏占位值(MASK_PREFIX 开头)的 api_key 时保留原值。"""
        merged = self.load()
        for k in PERSIST_FIELDS:
            if k not in patch or patch[k] is None:
                continue
            if k == "api_key" and str(patch[k]).startswith(MASK_PREFIX):
                continue  # 前端原样回传的脱敏值,不覆盖真实 Key
            merged[k] = patch[k]
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps({k: merged[k] for k in PERSIST_FIELDS}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return merged
