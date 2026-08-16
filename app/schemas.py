"""API 请求/响应模型:所有外部输入都在此做长度与范围校验。"""

from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["openai", "anthropic", "mock"]


# ---------------- 设置 ----------------
class SettingsIn(BaseModel):
    provider: Provider = "openai"
    model: str = Field("", max_length=100)
    base_url: str = Field("", max_length=500)
    api_key: str = Field("", max_length=500)
    temperature: float = Field(0.8, ge=0, le=2)
    chapter_words: int = Field(2500, ge=300, le=20000)


# ---------------- 项目 ----------------
class ProjectIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    idea: str = Field("", max_length=5000)
    genre: str = Field("", max_length=100)


class ProjectPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    idea: str | None = Field(None, max_length=5000)
    genre: str | None = Field(None, max_length=100)
    premise: str | None = Field(None, max_length=50000)
    characters: list[dict] | None = Field(None, max_length=100)
    outline: list[dict] | None = Field(None, max_length=1000)


# ---------------- 生成 ----------------
class PremiseIn(BaseModel):
    idea: str = Field("", max_length=5000)
    genre: str = Field("", max_length=100)


class CountIn(BaseModel):
    count: int = Field(5, ge=1, le=20)


class ChaptersIn(BaseModel):
    num_chapters: int = Field(12, ge=1, le=200)


# ---------------- 章节 ----------------
class ChapterAddIn(BaseModel):
    title: str = Field("", max_length=200)


class ChapterIn(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(None, max_length=500000)
    summary: str | None = Field(None, max_length=5000)


class InstructionIn(BaseModel):
    instruction: str = Field("", max_length=2000)
