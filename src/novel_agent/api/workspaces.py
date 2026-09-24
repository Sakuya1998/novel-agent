"""工作区和成员管理 API。

旧的 ``/api/auth/users`` 接口在迁移窗口内继续保留；本模块提供面向工作区
领域的新契约，版本化请求通过 server 的 /api/v1 兼容层自动映射到这里。
"""

import sqlite3
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from novel_agent.api.dependencies import (
    require_principal,
    require_workspace_access,
    require_workspace_role,
)
from novel_agent.security import Principal, hash_password

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(default="", max_length=200)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=100)
    role: Literal["owner", "editor", "viewer"] = "viewer"


class MemberRoleUpdateRequest(BaseModel):
    role: Literal["owner", "editor", "viewer"]


def _store(request: Request):
    store = getattr(request.app.state, "novel_store", None)
    if store is None:
        raise HTTPException(503, "工作区存储尚未初始化")
    return store


def _audit(request: Request, action: str, principal: Principal, *, resource_type: str, resource_id: str, metadata=None):
    _store(request).append_audit_log(
        action,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata or {},
        ip_address=(request.client.host if request.client else "unknown"),
        user_agent=request.headers.get("user-agent", ""),
    )


@router.get("")
async def list_workspaces(
    request: Request,
    principal: Principal = Depends(require_principal),
) -> dict:
    workspace = _store(request).get_tenant(principal.tenant_id)
    if workspace is None:
        raise HTTPException(404, "工作区不存在")
    return {"items": [workspace], "has_more": False, "next_cursor": None}


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    request: Request,
    principal: Principal = Depends(require_workspace_access),
) -> dict:
    workspace = _store(request).get_tenant(workspace_id)
    if workspace is None:
        raise HTTPException(404, "工作区不存在")
    return workspace


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    workspace = _store(request).update_tenant_name(workspace_id, payload.name.strip())
    if workspace is None:
        raise HTTPException(404, "工作区不存在")
    _audit(request, "workspace.updated", principal, resource_type="workspace", resource_id=workspace_id)
    return workspace


@router.get("/{workspace_id}/members")
async def list_workspace_members(
    workspace_id: str,
    request: Request,
    principal: Principal = Depends(require_workspace_access),
) -> dict:
    return {"items": _store(request).list_users(workspace_id), "has_more": False, "next_cursor": None}


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def create_workspace_member(
    workspace_id: str,
    payload: MemberCreateRequest,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    user_id = f"user_{uuid4().hex}"
    email = payload.email.strip().lower() or f"{payload.username.lower()}@local.invalid"
    try:
        user = _store(request).create_user_in_tenant(
            user_id=user_id,
            tenant_id=workspace_id,
            username=payload.username.strip(),
            email=email,
            display_name=payload.display_name.strip() or payload.username.strip(),
            password_hash=hash_password(payload.password),
            role=payload.role,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "用户名或邮箱已存在") from exc
    _audit(
        request,
        "workspace.member_created",
        principal,
        resource_type="user",
        resource_id=user_id,
        metadata={"role": payload.role},
    )
    return {"user": user}


@router.patch("/{workspace_id}/members/{user_id}")
async def update_workspace_member(
    workspace_id: str,
    user_id: str,
    payload: MemberRoleUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    target = _store(request).get_user_in_tenant(user_id, workspace_id)
    if target is None:
        raise HTTPException(404, "成员不存在")
    if (
        target.get("role") == "owner"
        and payload.role != "owner"
        and _store(request).count_tenant_owners(workspace_id) <= 1
    ):
        raise HTTPException(409, "工作区必须至少保留一个所有者")
    updated = _store(request).update_user_role(user_id, workspace_id, payload.role)
    _audit(
        request,
        "workspace.member_role_updated",
        principal,
        resource_type="user",
        resource_id=user_id,
        metadata={"role": payload.role},
    )
    return {"user": updated}


@router.delete("/{workspace_id}/members/{user_id}")
async def remove_workspace_member(
    workspace_id: str,
    user_id: str,
    request: Request,
    principal: Principal = Depends(require_workspace_role("owner")),
) -> dict:
    target = _store(request).get_user_in_tenant(user_id, workspace_id)
    if target is None:
        raise HTTPException(404, "成员不存在")
    if user_id == principal.user_id:
        raise HTTPException(409, "不能移除当前登录用户")
    if target.get("role") == "owner" and _store(request).count_tenant_owners(workspace_id) <= 1:
        raise HTTPException(409, "工作区必须至少保留一个所有者")
    if not _store(request).remove_user_from_tenant(user_id, workspace_id):
        raise HTTPException(404, "成员不存在")
    _audit(request, "workspace.member_removed", principal, resource_type="user", resource_id=user_id)
    return {"deleted": True, "user_id": user_id}
