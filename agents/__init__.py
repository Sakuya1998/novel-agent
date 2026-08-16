"""Agent 包:7 个 Agent(Orchestrator + 6 专业 Agent)。

输出解析辅助:从 LLM 文本中稳健提取 YAML/JSON 结构。
"""

import json
import re


def extract_code_block(text: str, lang: str) -> str:
    """提取 ```lang ... ``` 代码块;无代码块则返回原文(去首尾空白)。"""
    pattern = rf"```{lang}\s*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def parse_yaml_block(text: str) -> list[dict]:
    """从 LLM 输出解析 YAML 列表(容忍代码块包裹与前后噪声)。"""
    import yaml

    block = extract_code_block(text, "yaml")
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        # 退化:截取首个列表型代码段重试
        m = re.search(r"^- .*$", block, re.MULTILINE)
        if not m:
            raise
        start = m.start()
        data = yaml.safe_load(block[start:])
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(f"YAML 解析结果不是列表: {type(data)}")
    return [item for item in data if isinstance(item, dict)]


def parse_json_block(text: str) -> list[dict]:
    """从 LLM 输出解析 JSON 数组(容忍代码块包裹与前后噪声)。"""
    block = extract_code_block(text, "json")
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        start, end = block.find("["), block.rfind("]")
        if start == -1 or end <= start:
            return []
        data = json.loads(block[start : end + 1])
    if not isinstance(data, list):
        data = [data]
    return [item for item in data if isinstance(item, dict)]


__all__ = ["extract_code_block", "parse_yaml_block", "parse_json_block"]
