"""模型服务档案与三类全局路由的 FastAPI 接口。"""

from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator

from models.model_settings import (
    InvalidModelRouteError,
    ModelProfileNotFoundError,
    ModelSecretError,
    ModelSettingsError,
    ModelSettingsStore,
    ProfileInUseError,
    ProviderName,
)
from models.resolver import ModelConnectionError, ModelResolver

router = APIRouter(prefix="/api/model-settings", tags=["model-settings"])


class ProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: ProviderName
    base_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=1000)
    clear_api_key: bool = False
    chat_models: list[str] = Field(default_factory=list, max_length=50)
    embedding_models: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("name", "base_url", "api_key")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("chat_models", "embedding_models")
    @classmethod
    def validate_model_names(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 200 for value in cleaned):
            raise ValueError("模型名称不能超过 200 个字符")
        return list(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def validate_compatible_url(self):
        if self.provider in {"deepseek", "qwen", "openai_compatible"}:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("OpenAI 兼容服务必须配置有效的 HTTP(S) API 地址")
        return self


class RouteTarget(BaseModel):
    profile_id: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=200)

    @field_validator("profile_id", "model_name")
    @classmethod
    def strip_target(cls, value: str) -> str:
        return value.strip()


class RoutesWrite(BaseModel):
    creative: RouteTarget
    analysis: RouteTarget
    embedding: RouteTarget


class ConnectionTestRequest(BaseModel):
    kind: Literal["chat", "embedding"]
    model_name: str = Field(min_length=1, max_length=200)

    @field_validator("model_name")
    @classmethod
    def strip_model_name(cls, value: str) -> str:
        return value.strip()


def _store(request: Request) -> ModelSettingsStore:
    store = getattr(request.app.state, "model_settings_store", None)
    if store is None:
        raise HTTPException(503, "模型设置存储尚未初始化")
    return store


def _ensure_writable(request: Request) -> None:
    if int(getattr(request.app.state, "active_streams", 0)) > 0:
        raise HTTPException(409, "小说创作正在运行，完成或暂停后才能修改模型设置")


def _raise_store_error(exc: ModelSettingsError) -> None:
    if isinstance(exc, ModelProfileNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, (ProfileInUseError, ModelSecretError)):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, InvalidModelRouteError):
        raise HTTPException(422, str(exc)) from exc
    raise HTTPException(422, str(exc)) from exc


@router.get("")
async def get_model_settings(request: Request) -> dict:
    try:
        return _store(request).get_public_settings()
    except ModelSettingsError as exc:
        _raise_store_error(exc)


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_model_profile(request: Request, payload: ProfileWrite) -> dict:
    _ensure_writable(request)
    try:
        return _store(request).create_profile(**payload.model_dump(exclude={"clear_api_key"}))
    except ModelSettingsError as exc:
        _raise_store_error(exc)


@router.put("/profiles/{profile_id}")
async def update_model_profile(profile_id: str, request: Request, payload: ProfileWrite) -> dict:
    _ensure_writable(request)
    try:
        return _store(request).update_profile(profile_id, **payload.model_dump())
    except ModelSettingsError as exc:
        _raise_store_error(exc)


@router.delete("/profiles/{profile_id}")
async def delete_model_profile(profile_id: str, request: Request) -> dict:
    _ensure_writable(request)
    try:
        if not _store(request).delete_profile(profile_id):
            raise HTTPException(404, "模型服务不存在")
        return {"deleted": True, "profile_id": profile_id}
    except ModelSettingsError as exc:
        _raise_store_error(exc)


@router.put("/routes")
async def update_model_routes(request: Request, payload: RoutesWrite) -> dict:
    _ensure_writable(request)
    try:
        return _store(request).save_routes(payload.model_dump())
    except ModelSettingsError as exc:
        _raise_store_error(exc)


@router.post("/profiles/{profile_id}/test")
async def test_model_profile(
    profile_id: str,
    request: Request,
    payload: ConnectionTestRequest,
) -> dict:
    _ensure_writable(request)
    resolver = ModelResolver(
        config=request.app.state.config,
        store=_store(request),
    )
    try:
        return await resolver.test_profile(profile_id, payload.kind, payload.model_name)
    except ModelProfileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ModelConnectionError, ModelSettingsError) as exc:
        raise HTTPException(422, str(exc)) from exc
