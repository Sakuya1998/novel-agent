"""应用配置:默认值 < data/config.json < 环境变量。"""
import json
import os
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NOVEL_AGENT_DATA", _ROOT / "data"))
CONFIG_FILE = DATA_DIR / "config.json"

PROVIDER_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "mock": "mock",
}

DEFAULT_SETTINGS: Dict[str, Any] = {
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

# settings 文件中持久化的字段
PERSIST_FIELDS = ["provider", "model", "base_url", "api_key", "temperature", "chapter_words"]


def _file_settings() -> Dict[str, Any]:
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k in PERSIST_FIELDS}
    except Exception:
        pass
    return {}


def load_settings() -> Dict[str, Any]:
    s: Dict[str, Any] = dict(DEFAULT_SETTINGS)
    s.update(_file_settings())
    for key, env in ENV_KEYS.items():
        val = os.environ.get(env)
        if val not in (None, ""):
            if key in ("temperature",):
                try:
                    s[key] = float(val)
                except ValueError:
                    pass
            elif key in ("chapter_words",):
                try:
                    s[key] = int(val)
                except ValueError:
                    pass
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


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = load_settings()
    for k in PERSIST_FIELDS:
        if k in patch and patch[k] is not None:
            merged[k] = patch[k]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({k: merged[k] for k in PERSIST_FIELDS}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_settings()
