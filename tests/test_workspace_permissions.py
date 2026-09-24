"""工作区领域 API、角色权限和跨租户隔离测试。"""

import pytest
from httpx import ASGITransport, AsyncClient

from novel_agent.api import server


@pytest.fixture
async def workspace_api(tmp_path, monkeypatch):
    from novel_agent.config import Config
    from novel_agent.memory.sql_store import NovelStore

    cfg = Config(
        auth_enabled=True,
        sqlite_db_path=str(tmp_path / "workspace.db"),
        chroma_persist_dir=str(tmp_path / "chroma"),
        checkpoint_db_path=str(tmp_path / "checkpoints.db"),
        model_secret_key_path=str(tmp_path / "data" / "model-settings.key"),
    )
    cfg.ensure_dirs()
    isolated = NovelStore(cfg)
    monkeypatch.setattr(server, "cfg", cfg)
    monkeypatch.setattr(server, "store", isolated)
    monkeypatch.setattr("novel_agent.graph.nodes._store", isolated)
    async with server.lifespan(server.app):
        yield server


async def _client(api):
    return AsyncClient(transport=ASGITransport(app=api.app), base_url="http://test")


async def _register(client, username: str, tenant_name: str):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "strong-password",
            "tenant_name": tenant_name,
        },
    )
    assert response.status_code == 201
    body = response.json()
    # 下面的 API 请求使用 bearer token；清掉注册接口写入的 cookie，避免
    # cookie transport 触发 CSRF 校验并覆盖 Authorization 头。
    client.cookies.clear()
    return body["user"], {"Authorization": f"Bearer {body['access_token']}"}


async def test_workspace_contract_returns_current_workspace_and_members(workspace_api):
    async with await _client(workspace_api) as client:
        owner, headers = await _register(client, "workspace_owner", "协作工作区")
        listed = await client.get("/api/v1/workspaces", headers=headers)
        fetched = await client.get(f"/api/v1/workspaces/{owner['tenant_id']}", headers=headers)
        members = await client.get(f"/api/v1/workspaces/{owner['tenant_id']}/members", headers=headers)

    assert listed.status_code == fetched.status_code == members.status_code == 200
    assert listed.json()["items"] == [fetched.json()]
    assert fetched.json()["name"] == "协作工作区"
    assert [item["username"] for item in members.json()["items"]] == ["workspace_owner"]
    assert "password_hash" not in members.json()["items"][0]


async def test_workspace_roles_and_member_lifecycle(workspace_api):
    async with await _client(workspace_api) as client:
        owner, owner_headers = await _register(client, "lifecycle_owner", "生命周期工作区")
        workspace_id = owner["tenant_id"]
        created = await client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={
                "username": "lifecycle_editor",
                "password": "editor-password",
                "role": "editor",
            },
        )
        assert created.status_code == 201
        editor_id = created.json()["user"]["id"]
        editor_login = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "lifecycle_editor", "password": "editor-password"},
        )
        editor_headers = {"Authorization": f"Bearer {editor_login.json()['access_token']}"}
        client.cookies.clear()

        assert (
            await client.get(f"/api/v1/workspaces/{workspace_id}", headers=editor_headers)
        ).status_code == 200
        assert (
            await client.patch(
                f"/api/v1/workspaces/{workspace_id}",
                headers=editor_headers,
                json={"name": "不应成功"},
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/workspaces/{workspace_id}/members",
                headers=editor_headers,
                json={"username": "blocked_member", "password": "blocked-password"},
            )
        ).status_code == 403

        renamed = await client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            headers=owner_headers,
            json={"name": "已重命名工作区"},
        )
        role = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/members/{editor_id}",
            headers=owner_headers,
            json={"role": "viewer"},
        )
        removed = await client.delete(
            f"/api/v1/workspaces/{workspace_id}/members/{editor_id}",
            headers=owner_headers,
        )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "已重命名工作区"
    assert role.status_code == 200
    assert role.json()["user"]["role"] == "viewer"
    assert removed.status_code == 200
    assert removed.json() == {"deleted": True, "user_id": editor_id}


async def test_workspace_access_is_tenant_scoped_and_owner_cannot_remove_self(workspace_api):
    async with await _client(workspace_api) as client:
        first, first_headers = await _register(client, "tenant_one", "工作区一")
        second, second_headers = await _register(client, "tenant_two", "工作区二")

        cross_read = await client.get(
            f"/api/v1/workspaces/{second['tenant_id']}",
            headers=first_headers,
        )
        cross_members = await client.get(
            f"/api/v1/workspaces/{second['tenant_id']}/members",
            headers=first_headers,
        )
        remove_self = await client.delete(
            f"/api/v1/workspaces/{first['tenant_id']}/members/{first['id']}",
            headers=first_headers,
        )
        own_workspace = await client.get(
            f"/api/v1/workspaces/{second['tenant_id']}",
            headers=second_headers,
        )

    assert cross_read.status_code == cross_members.status_code == 404
    assert remove_self.status_code == 409
    assert own_workspace.status_code == 200


async def test_viewer_is_read_only_for_workspace_api(workspace_api):
    async with await _client(workspace_api) as client:
        owner, owner_headers = await _register(client, "viewer_owner", "只读工作区")
        workspace_id = owner["tenant_id"]
        created = await client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            headers=owner_headers,
            json={
                "username": "workspace_viewer",
                "password": "viewer-password",
                "role": "viewer",
            },
        )
        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={"identifier": "workspace_viewer", "password": "viewer-password"},
        )
        viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
        client.cookies.clear()
        read = await client.get(f"/api/v1/workspaces/{workspace_id}/members", headers=viewer_headers)
        write = await client.patch(
            f"/api/v1/workspaces/{workspace_id}",
            headers=viewer_headers,
            json={"name": "越权修改"},
        )

    assert created.status_code == 201
    assert read.status_code == 200
    assert write.status_code == 403
