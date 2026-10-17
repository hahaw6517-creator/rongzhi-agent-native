"""后台用户管理：清单/重置密码/禁用/删除，以及禁用后的登录与接口拦截。"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from finbridge.web_api import create_app
from conftest import admin_app, admin_client, client, app, register_user, login_user, auth_headers, admin_headers, add_user_model  # noqa: F401


def test_admin_user_lifecycle(admin_client):
    """管理员可查看清单、重置密码、禁用/启用，且不能操作自己。"""
    register_user(admin_client, "life01", "secret123")
    rows = admin_client.get("/api/admin/users", headers=admin_headers(admin_client)).json()["list"]
    target = next(r for r in rows if r["username"] == "life01")
    assert target["disabled"] is False and target["role"] == 0

    # 重置密码：弱密码拒绝，正常重置后旧密码失效、新密码可登录
    uid = target["id"]
    h = admin_headers(admin_client)
    assert admin_client.post(f"/api/admin/users/{uid}/reset-password", json={"password": "123"}, headers=h).status_code == 400
    assert admin_client.post(f"/api/admin/users/{uid}/reset-password", json={"password": "brand-new-9"}, headers=h).status_code == 200
    with pytest.raises(Exception):
        login_user(admin_client, "life01", "secret123")
    assert login_user(admin_client, "life01", "brand-new-9")["token"]

    # 禁用：登录被拒；启用后恢复
    assert admin_client.post(f"/api/admin/users/{uid}/status", json={"disabled": True}, headers=h).status_code == 200
    with pytest.raises(Exception):
        login_user(admin_client, "life01", "brand-new-9")
    assert admin_client.post(f"/api/admin/users/{uid}/status", json={"disabled": False}, headers=h).status_code == 200
    assert login_user(admin_client, "life01", "brand-new-9")["token"]

    # 自我保护：不能禁用/删除自己
    me = next(r for r in admin_client.get("/api/admin/users", headers=h).json()["list"] if r["role"] == 1)
    assert admin_client.post(f"/api/admin/users/{me['id']}/status", json={"disabled": True}, headers=h).status_code == 400
    assert admin_client.delete(f"/api/admin/users/{me['id']}", headers=h).status_code == 400


def test_disabled_user_token_is_rejected(admin_app, tmp_path):
    """禁用账户的既有会话立即失效，启用后恢复；删除账户级联清理数据。"""
    with TestClient(create_app(database_path=tmp_path / "u.sqlite3")) as client:
        data = register_user(client, "victim", "secret123", "受害者")
        victim_headers = auth_headers(data["token"])
        # 产生归属数据：一条历史分析 + 自配模型
        assert client.post("/api/runs", json={"goal": "风险分析"}, headers=victim_headers).status_code == 202
        add_user_model(client, data["token"])
        h = admin_headers(client)
        uid = next(r for r in client.get("/api/admin/users", headers=h).json()["list"] if r["username"] == "victim")["id"]

        assert client.post(f"/api/admin/users/{uid}/status", json={"disabled": True}, headers=h).status_code == 200
        assert client.get("/api/ai/models", headers=victim_headers).status_code == 403
        assert client.post(f"/api/admin/users/{uid}/status", json={"disabled": False}, headers=h).status_code == 200
        assert client.get("/api/ai/models", headers=victim_headers).status_code == 200

        assert client.delete(f"/api/admin/users/{uid}", headers=h).status_code == 200
        rows = client.get("/api/admin/users", headers=h).json()["list"]
        assert all(r["username"] != "victim" for r in rows)


def test_user_management_requires_admin(client):
    """普通用户与访客无法访问用户管理接口（首个注册者自动是管理员，用第二个用户验证）。"""
    register_user(client, "owner01", "secret123")  # 首个注册 → 管理员
    data = register_user(client, "plain01", "secret123")
    h = auth_headers(data["token"])
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=h).status_code == 403
    assert client.post("/api/admin/users/1/reset-password", json={"password": "x"*8}, headers=h).status_code == 403
    assert client.post("/api/admin/users/1/status", json={"disabled": True}, headers=h).status_code == 403
    assert client.delete("/api/admin/users/1", headers=h).status_code == 403
