"""AI 模型配置接口与解析优先级测试：用户多配置/平台托管/供应商注册表/历史对话，全部走本地假依赖。"""
from __future__ import annotations

import sqlite3

import pytest
from starlette.testclient import TestClient

from conftest import (
    PLATFORM_KEY, USER_KEY, add_platform_model, add_user_model, admin_headers,
    auth_headers, register_user,
)
from finbridge.config import Settings
from finbridge.model_resolver import resolve_llm_settings


def test_user_model_crud_masks_key_and_encrypts_at_rest(client):
    data = register_user(client)
    headers = auth_headers(data["token"])
    add_user_model(client, data["token"])
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["selectedId"] is not None  # 首套自动「使用中」
    item = models["list"][0]
    assert item["apiKeyMasked"] == "uk-****dcba"
    assert USER_KEY not in str(item)
    # 数据库里只存密文
    with sqlite3.connect(client.app.state.store.path) as db:
        rows = db.execute("SELECT api_key_enc FROM ai_model").fetchall()
    assert rows and all(USER_KEY not in str(row) for row in rows)
    # 校验：地址必须 http(s)、必填字段、供应商须在注册表
    payload = {"provider": "deepseek", "protocol": "openai", "baseUrl": "https://x.example.test", "modelId": "m", "apiKey": "k"}
    assert client.post("/api/ai/models", json={**payload, "provider": "nope"}, headers=headers).status_code == 400
    assert client.post("/api/ai/models", json={**payload, "baseUrl": "ftp://x"}, headers=headers).status_code == 400
    assert client.post("/api/ai/models", json={**payload, "modelId": ""}, headers=headers).status_code == 400
    # 编辑：API Key 留空保留原值
    updated = client.put(f"/api/ai/models/{item['id']}", json={
        "provider": "deepseek", "protocol": "openai", "baseUrl": "https://user.example.test",
        "modelId": "user-model", "displayName": "改名", "apiKey": ""}, headers=headers)
    assert updated.status_code == 200
    after = updated.json()["models"]["list"][0]
    assert after["displayName"] == "改名"
    assert after["apiKeyMasked"] == item["apiKeyMasked"]
    # 删除后清空并回落为未选中
    assert client.delete(f"/api/ai/models/{item['id']}", headers=headers).json()["ok"] is True
    assert client.get("/api/ai/models", headers=headers).json()["selectedId"] is None


def test_user_model_limit_six_and_delete_fallback(client):
    data = register_user(client)
    headers = auth_headers(data["token"])
    ids = []
    for index in range(6):
        models = add_user_model(client, data["token"], model=f"m{index}", display_name=f"模型{index}")
        ids.append(max(item["id"] for item in models["list"]))
    seventh = client.post("/api/ai/models", json={
        "provider": "deepseek", "protocol": "openai", "baseUrl": "https://x.example.test", "modelId": "m6", "apiKey": "k"}, headers=headers)
    assert seventh.status_code == 400
    assert "最多添加 6 个模型" in seventh.json()["error"]
    # 删除「使用中」项（首套）后自动回落到最新一条；其余新增不抢占使用中
    selected = client.get("/api/ai/models", headers=headers).json()["selectedId"]
    assert selected == ids[0]
    client.delete(f"/api/ai/models/{selected}", headers=headers)
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["selectedId"] == max(ids)
    # 显式切换使用中
    client.put(f"/api/ai/models/{ids[1]}/select", headers=headers)
    assert client.get("/api/ai/models", headers=headers).json()["selectedId"] == ids[1]


def test_platform_model_select_and_remove(client, admin_client):
    admin = admin_headers(admin_client)
    add_platform_model(admin_client, admin)
    # 平台模型列表进入用户视图
    data = register_user(client)
    headers = auth_headers(data["token"])
    models = client.get("/api/ai/models", headers=headers).json()
    assert len(models["platform"]) == 1
    platform_id = models["platform"][0]["id"]
    # 未选用前 selectedId 为空；选用后平台项标记 isSelected，自配列表仍为空
    assert models["selectedId"] is None
    client.put(f"/api/ai/platform-models/{platform_id}/select", headers=headers)
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["platform"][0]["isSelected"] is True
    assert models["selectedId"] is None  # 平台引用行不进自配列表
    # 平台引用行占额度；已有引用时新增自配不自动「使用中」，平台选中保持（与 template 口径一致）
    add_user_model(client, data["token"])
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["platform"][0]["isSelected"] is True
    assert models["selectedId"] is None
    # 显式切换到自配后平台项不再 isSelected
    self_id = models["list"][0]["id"]
    client.put(f"/api/ai/models/{self_id}/select", headers=headers)
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["platform"][0]["isSelected"] is False
    assert models["selectedId"] == self_id
    # 移除平台引用：回落到自配配置；再次移除 404
    client.delete(f"/api/ai/platform-models/{platform_id}", headers=headers)
    models = client.get("/api/ai/models", headers=headers).json()
    assert models["platform"][0]["isSelected"] is False
    assert models["selectedId"] == self_id
    assert client.delete(f"/api/ai/platform-models/{platform_id}", headers=headers).status_code == 404


def test_resolution_priority_user_then_platform_then_env(client, admin_client):
    store = client.app.state.store
    # 环境变量兜底：无任何配置时回落 load_settings()
    fallback = resolve_llm_settings(store, None)
    assert fallback.base_url == "https://env.example.test"
    # 平台托管启用后匿名会话也可用，bootstrap 显示已配置
    admin = admin_headers(admin_client)
    add_platform_model(admin_client, admin)
    assert client.get("/api/bootstrap").json()["model_configured"] is True
    resolved = resolve_llm_settings(store, None)
    assert (resolved.base_url, resolved.model) == ("https://platform.example.test", "platform-model")
    # 登录用户选中自配后优先生效（平台引用存在时新增自配不自动选中，需显式切换）
    data = register_user(client)
    headers = auth_headers(data["token"])
    add_user_model(client, data["token"])
    uid = data["user"]["id"]
    models = client.get("/api/ai/models", headers=headers).json()
    client.put(f"/api/ai/models/{models['list'][0]['id']}/select", headers=headers)
    resolved = resolve_llm_settings(store, uid)
    assert (resolved.base_url, resolved.model) == ("https://user.example.test", "user-model")
    assert resolved.api_key == USER_KEY
    # 用户选用平台托管后切回平台配置
    models = client.get("/api/ai/models", headers=auth_headers(data["token"])).json()
    platform_id = models["platform"][0]["id"]
    client.put(f"/api/ai/platform-models/{platform_id}/select", headers=auth_headers(data["token"]))
    resolved = resolve_llm_settings(store, uid)
    assert (resolved.base_url, resolved.model) == ("https://platform.example.test", "platform-model")
    assert resolved.api_key == PLATFORM_KEY
    # 平台删除后回落环境变量
    admin_client.delete(f"/api/admin/platform-models/{platform_id}", headers=admin)
    assert resolve_llm_settings(store, uid).base_url == "https://env.example.test"


def test_admin_providers_crud_and_default_seed(admin_client):
    headers = admin_headers(admin_client)
    providers = admin_client.get("/api/admin/ai-providers", headers=headers).json()["list"]
    assert len(providers) == 10  # 默认种子供应商
    assert {p["providerKey"] for p in providers} >= {"deepseek", "qwen", "kimi", "zhipu"}
    # 用户侧只看到启用的供应商
    data = register_user(admin_client)
    visible = admin_client.get("/api/ai/providers", headers=auth_headers(data["token"])).json()["list"]
    assert len(visible) == 10
    # 新增/重名/格式校验
    created = admin_client.post("/api/admin/ai-providers", json={
        "name": "测试供应", "providerKey": "test_prov", "protocol": "openai",
        "baseUrl": "https://api.test.example", "consoleUrl": "https://console.test.example",
        "modelDocUrl": "https://docs.test.example", "sortOrder": 99}, headers=headers)
    assert created.status_code == 200
    dup = admin_client.post("/api/admin/ai-providers", json={"name": "重复", "providerKey": "test_prov"}, headers=headers)
    assert dup.status_code == 409
    bad = admin_client.post("/api/admin/ai-providers", json={"name": "坏标识", "providerKey": "BAD-KEY"}, headers=headers)
    assert bad.status_code == 400
    # 停用后用户侧不可见
    item = created.json()["item"]
    admin_client.put(f"/api/admin/ai-providers/{item['id']}", json={**item, "enabled": False}, headers=headers)
    visible = admin_client.get("/api/ai/providers", headers=auth_headers(data["token"])).json()["list"]
    assert item["id"] not in {p["id"] for p in visible}
    # 删除
    assert admin_client.delete(f"/api/admin/ai-providers/{item['id']}", headers=headers).json()["ok"] is True


def test_admin_platform_model_crud_masks_key(admin_client):
    headers = admin_headers(admin_client)
    add_platform_model(admin_client, headers)
    listing = admin_client.get("/api/admin/platform-models", headers=headers).json()["list"]
    item = listing[0]
    assert item["keyMasked"] == "pk-****cdef"
    assert PLATFORM_KEY not in str(item)
    # 匿名与普通用户都不可管理
    assert admin_client.get("/api/admin/platform-models").status_code == 401
    # 编辑留空 apiKey 保留原密钥
    updated = admin_client.put(f"/api/admin/platform-models/{item['id']}", json={
        "name": "平台托管改", "protocol": "openai", "baseUrl": "https://platform.example.test",
        "modelId": "platform-model", "apiKey": "", "enabled": True, "sortOrder": 0}, headers=headers)
    assert updated.status_code == 200
    after = admin_client.get("/api/admin/platform-models", headers=headers).json()["list"][0]
    assert after["name"] == "平台托管改"
    assert after["keyMasked"] == item["keyMasked"]
    # 删除后清空
    assert admin_client.delete(f"/api/admin/platform-models/{item['id']}", headers=headers).json()["ok"] is True
    assert admin_client.get("/api/admin/platform-models", headers=headers).json()["list"] == []


def test_history_list_delete_clear(client):
    data = register_user(client)
    uid = data["user"]["id"]
    headers = auth_headers(data["token"])
    auth = client.app.state.auth
    auth.log_conversation(uid, "分析一下毛利率", "毛利率稳定在 28% 左右", "run-1")
    auth.log_conversation(uid, "如何优化应收账款", "建议缩短账期并引入保理", "run-1")
    listing = client.get("/api/ai/history", headers=headers).json()["list"]
    assert [item["question"] for item in listing] == ["如何优化应收账款", "分析一下毛利率"]  # 倒序
    assert listing[0]["runId"] == "run-1"
    # 另一用户看不到这批记录
    other = register_user(client, username="user02", password="secret456", nickname="二号")
    assert client.get("/api/ai/history", headers=auth_headers(other["token"])).json()["list"] == []
    # 删除单条与清空
    target = listing[0]["id"]
    assert client.delete(f"/api/ai/history/{target}", headers=headers).json()["ok"] is True
    assert client.delete(f"/api/ai/history/{target}", headers=headers).status_code == 404
    assert len(client.get("/api/ai/history", headers=headers).json()["list"]) == 1
    assert client.delete("/api/ai/history", headers=headers).json()["ok"] is True
    assert client.get("/api/ai/history", headers=headers).json()["list"] == []


def test_connectivity_test_reports_unreachable_endpoint_without_leaking_key(admin_client):
    headers = admin_headers(admin_client)
    add_platform_model(admin_client, headers, base_url="http://127.0.0.1:9")
    listing = admin_client.get("/api/admin/platform-models", headers=headers).json()["list"]
    response = admin_client.post(f"/api/admin/platform-models/{listing[0]['id']}/test", headers=headers)
    assert response.status_code == 502
    assert PLATFORM_KEY not in response.text


def test_master_key_from_env_takes_precedence(admin_client, monkeypatch):
    # 设置 FINBRIDGE_ENC_KEY 时主密钥走环境变量，两个配置能正常加解密
    from finbridge.secret_box import generate_master_key
    monkeypatch.setenv("FINBRIDGE_ENC_KEY", generate_master_key())
    headers = admin_headers(admin_client)
    add_platform_model(admin_client, headers)
    with sqlite3.connect(admin_client.app.state.store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM app_meta WHERE key='enc_key'").fetchone()[0] == 0
    assert admin_client.get("/api/admin/platform-models", headers=headers).json()["list"][0]["keyMasked"] == "pk-****cdef"


def test_seed_platform_from_env_when_table_empty(tmp_path, monkeypatch):
    """环境变量配置了 DEEPSEEK_API_KEY 且托管为空时，启动自动播种 DeepSeek 托管模型。

    密钥 Fernet 加密落库（明文不进库）；重启幂等不重复播种。
    """
    from conftest import _make_app
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings(None, "https://env.example.test", "env-model"))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("FINBRIDGE_ENC_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key-123456")
    with TestClient(_make_app(tmp_path)) as browser:
        with sqlite3.connect(browser.app.state.store.path) as db:
            rows = db.execute("SELECT name, provider, model_id, api_key_enc FROM ai_platform_model").fetchall()
        assert len(rows) == 1
        name, provider, model_id, enc = rows[0]
        assert (name, provider, model_id) == ("DeepSeek 官方", "deepseek", "deepseek-chat")
        assert "sk-env-deepseek-key-123456" not in enc  # 只存密文
    # 幂等：同一数据库重启，托管表仍只有一条
    with TestClient(_make_app(tmp_path)) as browser:
        with sqlite3.connect(browser.app.state.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM ai_platform_model").fetchone()[0] == 1


def test_seed_platform_skipped_without_env_or_existing_models(tmp_path, monkeypatch):
    """未配置环境变量密钥、或托管表已有模型时不播种。"""
    from conftest import _make_app
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings(None, "https://env.example.test", "env-model"))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("FINBRIDGE_ENC_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(_make_app(tmp_path)) as browser:
        with sqlite3.connect(browser.app.state.store.path) as db:
            assert db.execute("SELECT COUNT(*) FROM ai_platform_model").fetchone()[0] == 0
    # 已有托管模型时，设置了环境变量也不追加
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key-123456")
    with TestClient(_make_app(tmp_path)) as browser:
        auth = browser.app.state.auth
        auth.seed_platform_from_env()
        auth.seed_platform_from_env()
        with sqlite3.connect(auth.path) as db:
            assert db.execute("SELECT COUNT(*) FROM ai_platform_model").fetchone()[0] == 1


def test_seed_platform_not_reseeded_over_admin_models(admin_client, monkeypatch):
    """管理员已配置托管模型时，设置环境变量重启也不追加播种。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key-123456")
    headers = admin_headers(admin_client)
    add_platform_model(admin_client, headers)
    admin_client.app.state.auth.bootstrap()
    with sqlite3.connect(admin_client.app.state.store.path) as db:
        names = [row[0] for row in db.execute("SELECT name FROM ai_platform_model").fetchall()]
    assert names == ["平台托管"]
