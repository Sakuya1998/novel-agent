"""共享的认证、工作区和角色权限依赖。"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from novel_agent.security import Principal


def require_principal(request: Request) -> Principal:
    """返回当前请求身份；未认证请求统一返回 401。"""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(401, "需要登录")
    return principal


def require_role(*roles: str) -> Callable:
    """构造一个限制角色的 FastAPI 依赖。"""
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(403, "当前角色没有执行此操作的权限")
        return principal

    return dependency


def require_workspace_access(
    workspace_id: str,
    principal: Principal = Depends(require_principal),
) -> Principal:
    """确认路径工作区属于当前身份；跨工作区统一伪装为 404。"""
    if workspace_id != principal.tenant_id:
        raise HTTPException(404, "工作区不存在")
    return principal


def require_workspace_role(*roles: str) -> Callable:
    """构造同时检查工作区归属和角色的依赖。"""
    allowed = frozenset(roles)

    def dependency(
        workspace_id: str,
        principal: Principal = Depends(require_principal),
    ) -> Principal:
        if workspace_id != principal.tenant_id:
            raise HTTPException(404, "工作区不存在")
        if principal.role not in allowed:
            raise HTTPException(403, "当前角色没有执行此操作的权限")
        return principal

    return dependency
