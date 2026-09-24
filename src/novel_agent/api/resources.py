"""版本化工作区资源中心 API。"""

import sqlite3
from functools import partial
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from novel_agent.api.dependencies import require_workspace_access, require_workspace_role
from novel_agent.config import STYLE_PROFILES
from novel_agent.models.workspace_resources import (
    ResourcePayloadError,
    normalize_resource_payload,
    system_style_resource,
    system_style_resources,
)
from novel_agent.security import Principal

router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["workspace-resources"])
canonical_router = APIRouter(prefix="/api/workspaces/{workspace_id}", tags=["workspace-resources"])
ResourceKind = Literal["content_types", "styles", "creative_templates", "quality_policies"]
RESOURCE_PATH_KINDS = {
    "content-types": "content_types",
    "content_types": "content_types",
    "styles": "styles",
    "creative-templates": "creative_templates",
    "creative_templates": "creative_templates",
    "quality-policies": "quality_policies",
    "quality_policies": "quality_policies",
}


class ResourceWrite(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("key", "name", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ResourceUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    payload: dict[str, Any] | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("key", "name", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return " ".join(value.strip().split()) if value is not None else None


class ResourceTransition(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


class ResourceCopy(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


def _store(request: Request):
    store = getattr(request.app.state, "novel_store", None)
    if store is None:
        raise HTTPException(503, "工作区资源存储尚未初始化")
    return store


def _kind(kind: str) -> ResourceKind:
    normalized = RESOURCE_PATH_KINDS.get(kind)
    if normalized is None:
        raise HTTPException(404, "资源类型不存在")
    return normalized  # type: ignore[return-value]


def _audit(
    request: Request,
    action: str,
    principal: Principal,
    *,
    resource_id: str,
    kind: str,
    metadata: dict | None = None,
) -> None:
    _store(request).append_audit_log(
        action,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        resource_type=kind,
        resource_id=resource_id,
        metadata=metadata or {},
        ip_address=(request.client.host if request.client else "unknown"),
        user_agent=request.headers.get("user-agent", ""),
    )


def _normalize(kind: ResourceKind, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return normalize_resource_payload(kind, payload)
    except ResourcePayloadError as exc:
        raise HTTPException(422, str(exc)) from exc


def _ensure_key_available(kind: ResourceKind, key: str) -> None:
    if kind == "styles" and key in STYLE_PROFILES:
        raise HTTPException(409, "系统风格 key 不能被工作区资源占用")


def _find_resource(request: Request, workspace_id: str, kind: ResourceKind, resource_id: str) -> dict:
    resource = _store(request).get_resource(workspace_id, kind, resource_id)
    if resource is None and kind == "styles":
        resource = system_style_resource(workspace_id, resource_id)
    if resource is None:
        raise HTTPException(404, "资源不存在")
    return resource


@router.get("/{resource_kind}")
async def list_resources(
    workspace_id: str,
    resource_kind: str,
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", pattern=r"^(draft|published|disabled)$"),
    principal: Principal = Depends(require_workspace_access),
) -> dict:
    kind = _kind(resource_kind)
    items = _store(request).list_resources(workspace_id, kind, status_filter)
    if kind == "styles":
        system_items = system_style_resources(workspace_id)
        if status_filter in {None, "published"}:
            items = system_items + items
    return {"items": items, "has_more": False, "next_cursor": None}


@router.post("/{resource_kind}", status_code=status.HTTP_201_CREATED)
async def create_resource(
    workspace_id: str,
    resource_kind: str,
    payload: ResourceWrite,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    kind = _kind(resource_kind)
    _ensure_key_available(kind, payload.key)
    normalized = _normalize(kind, payload.payload)
    if kind == "content_types" and normalized.get("parent_id"):
        parent = _store(request).get_resource(workspace_id, kind, str(normalized["parent_id"]))
        if parent is None:
            raise HTTPException(422, "父级内容类型不存在")
    try:
        resource = _store(request).create_resource(
            resource_id=f"resource_{uuid4().hex[:16]}",
            tenant_id=workspace_id,
            kind=kind,
            key=payload.key,
            name=payload.name,
            description=payload.description,
            payload=normalized,
            created_by=principal.user_id,
        )
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc) or "资源 key 已存在") from exc
    _audit(request, "workspace.resource_created", principal, resource_id=resource["id"], kind=kind)
    return resource


@router.get("/{resource_kind}/{resource_id}")
async def get_resource(
    workspace_id: str,
    resource_kind: str,
    resource_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(require_workspace_access),
) -> dict:
    kind = _kind(resource_kind)
    if version is not None and kind == "styles" and resource_id.startswith("system_style_") and version != 1:
        raise HTTPException(404, "资源版本不存在")
    resource = (
        _store(request).get_resource(workspace_id, kind, resource_id, version)
        or (system_style_resource(workspace_id, resource_id) if kind == "styles" and version in {None, 1} else None)
    )
    if resource is None:
        raise HTTPException(404, "资源不存在")
    return resource


@router.get("/{resource_kind}/{resource_id}/versions")
async def list_resource_versions(
    workspace_id: str,
    resource_kind: str,
    resource_id: str,
    request: Request,
    principal: Principal = Depends(require_workspace_access),
) -> dict:
    kind = _kind(resource_kind)
    if kind == "styles" and resource_id.startswith("system_style_"):
        return {"items": [system_style_resource(workspace_id, resource_id)], "has_more": False, "next_cursor": None}
    if _store(request).get_resource(workspace_id, kind, resource_id) is None:
        raise HTTPException(404, "资源不存在")
    return {
        "items": _store(request).list_resource_versions(workspace_id, kind, resource_id),
        "has_more": False,
        "next_cursor": None,
    }


@router.patch("/{resource_kind}/{resource_id}")
async def update_resource(
    workspace_id: str,
    resource_kind: str,
    resource_id: str,
    payload: ResourceUpdate,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    kind = _kind(resource_kind)
    current = _find_resource(request, workspace_id, kind, resource_id)
    if current["is_system"]:
        raise HTTPException(409, "系统资源只能复制后编辑")
    data = _normalize(kind, payload.payload if payload.payload is not None else current["payload"])
    _ensure_key_available(kind, payload.key or current["key"])
    if kind == "content_types" and data.get("parent_id"):
        parent = _store(request).get_resource(workspace_id, kind, str(data["parent_id"]))
        if parent is None:
            raise HTTPException(422, "父级内容类型不存在")
    try:
        updated = _store(request).update_resource(
            tenant_id=workspace_id,
            kind=kind,
            resource_id=resource_id,
            key=payload.key or current["key"],
            name=payload.name or current["name"],
            description=payload.description if payload.description is not None else current["description"],
            payload=data,
            expected_version=payload.expected_version,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "资源 key 已存在") from exc
    if updated is None:
        raise HTTPException(404, "资源不存在")
    _audit(request, "workspace.resource_updated", principal, resource_id=resource_id, kind=kind)
    return updated


@router.post("/{resource_kind}/{resource_id}/publish")
async def publish_resource(
    workspace_id: str,
    resource_kind: str,
    resource_id: str,
    payload: ResourceTransition,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    kind = _kind(resource_kind)
    _find_resource(request, workspace_id, kind, resource_id)
    try:
        resource = _store(request).publish_resource(workspace_id, kind, resource_id, payload.expected_version)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if resource is None:
        raise HTTPException(404, "资源不存在")
    _audit(request, "workspace.resource_published", principal, resource_id=resource_id, kind=kind)
    return resource


@router.post("/{resource_kind}/{resource_id}/disable")
async def disable_resource(
    workspace_id: str,
    resource_kind: str,
    resource_id: str,
    payload: ResourceTransition,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    kind = _kind(resource_kind)
    current = _find_resource(request, workspace_id, kind, resource_id)
    if current["is_system"]:
        raise HTTPException(409, "系统资源不能停用")
    try:
        resource = _store(request).disable_resource(workspace_id, kind, resource_id, payload.expected_version)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if resource is None:
        raise HTTPException(404, "资源不存在")
    _audit(request, "workspace.resource_disabled", principal, resource_id=resource_id, kind=kind)
    return resource


@router.post("/styles/{resource_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_style_resource(
    workspace_id: str,
    resource_id: str,
    payload: ResourceCopy,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    source = _find_resource(request, workspace_id, "styles", resource_id)
    _ensure_key_available("styles", payload.key)
    try:
        copied = _store(request).create_resource(
            resource_id=f"resource_{uuid4().hex[:16]}",
            tenant_id=workspace_id,
            kind="styles",
            key=payload.key,
            name=payload.name,
            description=payload.description or f"复制自 {source['name']}",
            payload=source["payload"],
            created_by=principal.user_id,
        )
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc) or "资源 key 已存在") from exc
    _audit(
        request,
        "workspace.resource_copied",
        principal,
        resource_id=copied["id"],
        kind="styles",
        metadata={"source_id": resource_id},
    )
    return copied


# Publish explicit paths in the OpenAPI contract while retaining the generic
# route above for migration-time underscore aliases.
for _path_kind, _resource_kind in (
    ("content-types", "content_types"),
    ("styles", "styles"),
    ("creative-templates", "creative_templates"),
    ("quality-policies", "quality_policies"),
):
    canonical_router.add_api_route(
        f"/{_path_kind}",
        partial(list_resources, resource_kind=_resource_kind),
        methods=["GET"],
        name=f"list_{_resource_kind}",
    )
    canonical_router.add_api_route(
        f"/{_path_kind}",
        partial(create_resource, resource_kind=_resource_kind),
        methods=["POST"],
        name=f"create_{_resource_kind}",
        status_code=status.HTTP_201_CREATED,
    )
    canonical_router.add_api_route(
        f"/{_path_kind}/{{resource_id}}",
        partial(get_resource, resource_kind=_resource_kind),
        methods=["GET"],
        name=f"get_{_resource_kind}",
    )
    canonical_router.add_api_route(
        f"/{_path_kind}/{{resource_id}}",
        partial(update_resource, resource_kind=_resource_kind),
        methods=["PATCH"],
        name=f"update_{_resource_kind}",
    )
    canonical_router.add_api_route(
        f"/{_path_kind}/{{resource_id}}/versions",
        partial(list_resource_versions, resource_kind=_resource_kind),
        methods=["GET"],
        name=f"list_{_resource_kind}_versions",
    )
    canonical_router.add_api_route(
        f"/{_path_kind}/{{resource_id}}/publish",
        partial(publish_resource, resource_kind=_resource_kind),
        methods=["POST"],
        name=f"publish_{_resource_kind}",
    )
    canonical_router.add_api_route(
        f"/{_path_kind}/{{resource_id}}/disable",
        partial(disable_resource, resource_kind=_resource_kind),
        methods=["POST"],
        name=f"disable_{_resource_kind}",
    )
