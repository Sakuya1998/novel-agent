"""Prompt 模板管理器(文档 8.2)。

集中管理 prompts/ 目录下的模板文件,提供:
- 加载与缓存({agent_name}.txt)
- 变量填充({{var}} 单花括号模板按文档约定,同时兼容 str.format 风格)
- 校验缺失变量
"""

import re
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent

# 单花括号变量: {title} / {chapter_number}(文档模板采用此风格,与 str.format 双花括号区分)
_VAR_PATTERN = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@lru_cache(maxsize=16)
def load_template(agent_name: str) -> str:
    """加载并缓存指定 Agent 的 Prompt 模板。

    Args:
        agent_name: Agent 名,对应 prompts/{agent_name}.txt

    Returns:
        模板文本(未填充)
    """
    path = PROMPT_DIR / f"{agent_name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 模板不存在: {path}")
    return path.read_text(encoding="utf-8")


def get_variables(agent_name: str) -> list[str]:
    """返回模板中声明的变量名列表(去重,保持出现顺序)。"""
    return list(dict.fromkeys(_VAR_PATTERN.findall(load_template(agent_name))))


def fill_template(agent_name: str, **kwargs) -> str:
    """加载模板并填充变量。

    Args:
        agent_name: Agent 名
        **kwargs: 模板变量值

    Returns:
        填充后的完整 Prompt

    Raises:
        KeyError: 存在未提供的变量(宁失败不默填,防止上下文缺失)
    """
    template = load_template(agent_name)
    required = set(get_variables(agent_name))
    missing = required - set(kwargs)
    if missing:
        raise KeyError(f"Prompt 模板 {agent_name} 缺少变量: {sorted(missing)}")

    def _sub(match: re.Match) -> str:
        return str(kwargs[match.group(1)])

    return _VAR_PATTERN.sub(_sub, template)


class PromptManager:
    """面向对象的模板管理入口(供需要多模板复用的调用方使用)。"""

    @staticmethod
    def load(agent_name: str) -> str:
        return load_template(agent_name)

    @staticmethod
    def fill(agent_name: str, **kwargs) -> str:
        return fill_template(agent_name, **kwargs)

    @staticmethod
    def variables(agent_name: str) -> list[str]:
        return get_variables(agent_name)
