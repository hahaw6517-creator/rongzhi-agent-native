"""Web 层测试共享夹具与辅助：临时站点、假环境变量、验证码/注册/登录/模型辅助。

验证码明文通过 sqlite 读取（等价于 template DEBUG=1 的 debugCode 后门），全部走本地假依赖。
"""
from __future__ import annotations

import sqlite3

import pytest
from starlette.testclient import TestClient

from finbridge import web_api
from finbridge.config import Settings

PLATFORM_KEY = "pk-platform-1234567890abcdef"
USER_KEY = "uk-user-9876543210fedcba"
ADMIN_PASSWORD = "test-admin-123"


def _make_app(tmp_path):
    web = tmp_path / "web"
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>融智</title>", encoding="utf-8")
    (web / "admin.html").write_text("<!doctype html><title>管理</title>", encoding="utf-8")
    return web_api.create_app(database_path=tmp_path / "runtime.sqlite3", web_root=web)


@pytest.fixture
def app(tmp_path, monkeypatch):
    # 未设置 ADMIN_PASSWORD：首个注册用户自动成为管理员
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings(None, "https://env.example.test", "env-model"))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("FINBRIDGE_ENC_KEY", raising=False)
    return _make_app(tmp_path)


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    # ADMIN_PASSWORD 在建应用前设置：启动时播种管理员 admin
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings(None, "https://env.example.test", "env-model"))
    monkeypatch.delenv("FINBRIDGE_ENC_KEY", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    return _make_app(tmp_path)


@pytest.fixture
def client(app):
    with TestClient(app) as browser:
        yield browser


@pytest.fixture
def admin_client(admin_app):
    with TestClient(admin_app) as browser:
        yield browser


def captcha_pair(client) -> tuple[str, str]:
    """申请验证码并从库中读出明文。"""
    data = client.get("/api/auth/captcha").json()
    with sqlite3.connect(client.app.state.store.path) as db:
        code = db.execute("SELECT code FROM captchas WHERE id=?", (data["captchaId"],)).fetchone()[0]
    return data["captchaId"], code


def register_user(client, username="user01", password="secret123", nickname="测试用户"):
    captcha_id, code = captcha_pair(client)
    response = client.post("/api/auth/register", json={
        "username": username, "password": password, "nickname": nickname,
        "captchaId": captcha_id, "captchaCode": code})
    assert response.status_code == 200, response.text
    return response.json()


def login_user(client, username="user01", password="secret123"):
    captcha_id, code = captcha_pair(client)
    response = client.post("/api/auth/login", json={
        "username": username, "password": password, "captchaId": captcha_id, "captchaCode": code})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def settle(client, run_id: str) -> dict:
    """等待既有分析任务执行完成并返回结果（案例载入自动生成的任务用）。"""
    import time as _time
    for _ in range(200):
        run = client.get("/api/runs/" + run_id).json()
        if run["status"] != "执行中":
            assert run["status"] == "已完成", run
            return run
        _time.sleep(0.005)
    pytest.fail("Auto task did not complete")


def admin_headers(client) -> dict:
    """ADMIN_PASSWORD 播种的 admin 账号登录，返回 Bearer 头。"""
    data = login_user(client, "admin", ADMIN_PASSWORD)
    return auth_headers(data["token"])


def add_platform_model(client, headers, name="平台托管", base_url="https://platform.example.test",
                       model="platform-model", api_key=PLATFORM_KEY, **extra) -> dict:
    payload = {"name": name, "baseUrl": base_url, "modelId": model, "apiKey": api_key, **extra}
    response = client.post("/api/admin/platform-models", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def add_user_model(client, token, provider="deepseek", base_url="https://user.example.test",
                   model="user-model", api_key=USER_KEY, display_name="我的模型", **extra) -> dict:
    payload = {"provider": provider, "protocol": "openai", "baseUrl": base_url, "modelId": model,
               "displayName": display_name, "apiKey": api_key, **extra}
    response = client.post("/api/ai/models", json=payload, headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["models"]
