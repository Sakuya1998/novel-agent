"""Prompt 模板与解析工具测试。"""

import pytest

from agents import parse_json_block, parse_yaml_block
from prompts import fill_template, get_variables, load_template

ALL_TEMPLATES = [
    "world_builder",
    "character_designer",
    "plot_planner",
    "scene_writer",
    "style_editor",
    "consistency_checker",
]


def test_all_templates_loadable():
    for name in ALL_TEMPLATES:
        text = load_template(name)
        assert len(text) > 100, f"{name} 模板过短"


def test_variables_extracted():
    assert "style_prompt" in get_variables("scene_writer")
    assert "chapter_number" in get_variables("consistency_checker")
    assert "user_input" in get_variables("world_builder")


def test_fill_template_roundtrip():
    out = fill_template("world_builder", user_input="标题:测试\n类型:武侠")
    assert "标题:测试" in out
    assert "{user_input}" not in out


def test_fill_template_missing_var_raises():
    with pytest.raises(KeyError, match="user_input"):
        fill_template("world_builder")


def test_parse_yaml_block_plain_and_wrapped():
    plain = "- name: 甲\n  role: 主角\n- name: 乙\n  role: 反派\n"
    wrapped = f"好的,以下是角色:\n```yaml\n{plain}```\n请查收"
    assert parse_yaml_block(plain) == parse_yaml_block(wrapped)
    assert len(parse_yaml_block(wrapped)) == 2
    assert parse_yaml_block(wrapped)[0]["name"] == "甲"


def test_parse_json_block_with_noise():
    text = '检查完成:\n```json\n[{"type": "时间线", "severity": "high"}]\n```'
    issues = parse_json_block(text)
    assert issues[0]["severity"] == "high"

    # 无代码块的裸数组
    assert parse_json_block("[]") == []
    # 前后噪声中截取数组
    assert parse_json_block('结果如下 [{"type": "x"}] 以上')[0]["type"] == "x"

    with pytest.raises(ValueError, match="对象"):
        parse_json_block("[1, 2]")
