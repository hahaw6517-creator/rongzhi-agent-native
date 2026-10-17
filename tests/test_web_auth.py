"""认证体系测试：验证码一次性消费、注册校验、登录、JWT、管理员权限与播种。"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from conftest import ADMIN_PASSWORD, auth_headers, captcha_pair, login_user, register_user


def test_captcha_is_one_shot(client):
    # 同一验证码只能消费一次：注册用掉后再次登录必须重新获取
    data = client.get("/api/auth/captcha").json()
    import sqlite3
    with sqlite3.connect(client.app.state.store.path) as db:
        code = db.execute("SELECT code FROM captchas WHERE id=?", (data["captchaId"],)).fetchone()[0]
    first = client.post("/api/auth/register", json={
        "username": "user01", "password": "secret123", "captchaId": data["captchaId"], "captchaCode": code})
    assert first.status_code == 200, first.text
    again = client.post("/api/auth/login", json={
        "username": "user01", "password": "secret123", "captchaId": data["captchaId"], "captchaCode": code})
    assert again.status_code == 400
    assert again.json()["error"] == "验证码错误或已过期"


def test_register_validation_rules(client):
    # 用户名 3-32 位字母数字下划线、密码 ≥6、验证码必填且须正确
    assert client.post("/api/auth/register", json={"username": "ab", "password": "secret123", "captchaId": "x", "captchaCode": "y"}).status_code == 400
    assert client.post("/api/auth/register", json={"username": "用户名", "password": "secret123", "captchaId": "x", "captchaCode": "y"}).status_code == 400
    assert client.post("/api/auth/register", json={"username": "user01", "password": "123", "captchaId": "x", "captchaCode": "y"}).status_code == 400
    assert client.post("/api/auth/register", json={"username": "user01", "password": "secret123", "captchaId": "bad", "captchaCode": "BAD"}).status_code == 400
    register_user(client)
    # 重名 409（需通过合法验证码到达查重逻辑）
    captcha_id, code = captcha_pair(client)
    dup = client.post("/api/auth/register", json={
        "username": "user01", "password": "secret123", "captchaId": captcha_id, "captchaCode": code})
    assert dup.status_code == 409
    assert dup.json()["error"] == "用户名已被注册"


def test_login_and_me_with_jwt(client):
    # 错误口令 401；正确口令拿到 token 后 /api/auth/me 可用；无 token 401
    register_user(client)
    captcha_id, code = captcha_pair(client)
    wrong = client.post("/api/auth/login", json={
        "username": "user01", "password": "badpass", "captchaId": captcha_id, "captchaCode": code})
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "用户名或密码错误"
    data = login_user(client)
    assert data["user"]["username"] == "user01"
    me = client.get("/api/auth/me", headers=auth_headers(data["token"]))
    assert me.json()["user"]["nickname"] == "测试用户"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_first_user_becomes_admin_when_no_admin_exists(client):
    # 系统无管理员时首位注册者 role=1，之后注册的用户 role=0
    first = register_user(client, username="founder")
    second = register_user(client, username="member", password="secret456", nickname="成员")
    assert first["user"]["role"] == 1
    assert second["user"]["role"] == 0


def test_admin_password_seeds_admin_account(admin_client):
    # ADMIN_PASSWORD 播种 admin 账号，可直接登录后台
    data = login_user(admin_client, "admin", ADMIN_PASSWORD)
    assert data["user"]["role"] == 1
    assert data["user"]["nickname"] == "管理员"


def test_admin_guard_requires_role(client):
    # 无 ADMIN_PASSWORD 时首位注册者是管理员，第二位是普通用户；普通用户访问后台接口 403，匿名 401
    founder = register_user(client, username="founder")
    assert founder["user"]["role"] == 1
    member = register_user(client, username="member", password="secret456", nickname="成员")
    assert member["user"]["role"] == 0
    forbidden = client.get("/api/admin/platform-models", headers=auth_headers(member["token"]))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"] == "需要管理员权限"
    assert client.get("/api/admin/platform-models").status_code == 401


def test_ai_endpoints_require_login(client):
    # 模型与历史接口未登录一律 401
    for method, path in (("get", "/api/ai/models"), ("get", "/api/ai/providers"), ("get", "/api/ai/history")):
        assert getattr(client, method)(path).status_code == 401


def test_run_ownership_follows_account_across_sessions(client):
    """登录账户的分析记录跨浏览器会话可见；匿名会话相互隔离；会话清理不误删账户记录。"""
    from starlette.testclient import TestClient
    user = register_user(client)
    headers = auth_headers(user["token"])
    # 当前会话创建分析任务（登录态 → 记录归属账户；等待完成，避免 running 冲突）
    created = client.post("/api/runs", headers=headers, json={"goal": "融资组合", "profile": {"requested_amount": 1_500_000.}, "use_ai": False})
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    for _ in range(3000):
        status = client.get(f"/api/runs/{run_id}", headers=headers).json().get("status")
        if status != "执行中":
            break
        import time; time.sleep(.01)
    # 新浏览器会话 + 同一账户 token：历史分析仍可见，可读取详情
    other = TestClient(client.app)
    boot = other.get("/api/bootstrap", headers=headers).json()
    assert any(r["id"] == run_id for r in boot["runs"]), "跨会话账户历史分析缺失"
    assert other.get(f"/api/runs/{run_id}", headers=headers).status_code == 200
    # 匿名新会话看不到该记录
    anon = TestClient(client.app)
    assert not any(r["id"] == run_id for r in anon.get("/api/bootstrap").json()["runs"])
    assert anon.get(f"/api/runs/{run_id}").status_code == 404
    # 模拟原会话过期清理：账户记录必须保留
    import sqlite3
    with sqlite3.connect(client.app.state.store.path) as db:
        db.execute("DELETE FROM sessions WHERE id=(SELECT session_id FROM runs WHERE id=?)", (run_id,))
    client.get("/api/bootstrap", headers=headers)  # 触发清理逻辑
    survived = client.get(f"/api/runs/{run_id}", headers=headers)
    assert survived.status_code == 200, "会话清理误删了账户级分析记录"
    assert not any(r["id"] == run_id for r in client.get("/api/bootstrap").json()["runs"]), "匿名视角不应看到账户记录"


def test_orphan_demo_runs_claimed_by_admin_on_startup(admin_client):
    """启动回填：无归属历史分析按企业分组，每企业仅保留最新一条归属 admin，重复记录清理。"""
    import json
    import sqlite3
    # 伪造无归属历史记录：海天两条（重复，保留较新的）+ 任意企业一条
    with sqlite3.connect(admin_client.app.state.store.path) as db:
        rows = [
            ("FB-CLAIM-HAITIAN-OLD", "佛山市海天调味食品股份有限公司", 100.0),
            ("FB-CLAIM-HAITIAN-NEW", "佛山市海天调味食品股份有限公司", 200.0),
            ("FB-CLAIM-OTHER", "测试甲公司", 150.0),
        ]
        for run_id, company, created in rows:
            result = json.dumps({"id": run_id, "goal": "融资组合", "status": "已完成", "mode": "Python 快速通道", "fingerprint": "fake", "created_at": 1.0, "events": [],
                                 "data": {"company_name": company}, "outputs": {}, "profile": {"requested_amount": 1_500_000.}})
            db.execute("INSERT INTO runs(id,session_id,user_id,created,running,result) VALUES (?,?,NULL,?,0,?)",
                       (run_id, "orphan-session", created, result))
    # 重启应用触发回填（同一路径新建 app）
    from finbridge.web_api import create_app
    with TestClient(create_app(database_path=admin_client.app.state.store.path)) as restarted:
        data = login_user(restarted, "admin", ADMIN_PASSWORD)
        headers = auth_headers(data["token"])
        ids = [r["id"] for r in restarted.get("/api/bootstrap", headers=headers).json()["runs"]]
        assert "FB-CLAIM-HAITIAN-NEW" in ids and "FB-CLAIM-HAITIAN-OLD" not in ids, "海天重复记录未收敛为最新一条"
        assert "FB-CLAIM-OTHER" in ids, "其他企业记录不应被清理"
        # 数据库里重复记录已物理清理
        with sqlite3.connect(restarted.app.state.store.path) as db:
            left = db.execute("SELECT COUNT(*) FROM runs WHERE id='FB-CLAIM-HAITIAN-OLD'").fetchone()[0]
        assert left == 0, "重复的旧记录应被删除"


def test_startup_dedup_merges_orphan_with_owned_runs(admin_client):
    """启动回填去重范围覆盖 admin 名下已有记录：与无归属记录合并按企业收敛为一条，不影响其他用户。"""
    import json
    import sqlite3
    register_user(admin_client, username="user02", password="secret123", nickname="其他用户")
    with sqlite3.connect(admin_client.app.state.store.path) as db:
        rows = [
            # (run_id, 归属, created)：admin 名下海天(100)、无归属海天旧(50)、无归属海天新(300)、user02 名下海天(200)
            ("FB-OWN-HAITIAN", "(SELECT id FROM users WHERE username='admin')", 100.0),
            ("FB-ORPHAN-HAITIAN-OLD", "NULL", 50.0),
            ("FB-ORPHAN-HAITIAN-NEW", "NULL", 300.0),
            ("FB-USER02-HAITIAN", "(SELECT id FROM users WHERE username='user02')", 200.0),
        ]
        for run_id, owner, created in rows:
            result = json.dumps({"id": run_id, "goal": "融资组合", "status": "已完成", "mode": "Python 快速通道", "fingerprint": "fake", "created_at": 1.0, "events": [],
                                 "data": {"company_name": "佛山市海天调味食品股份有限公司"}, "outputs": {}, "profile": {"requested_amount": 1_500_000.}})
            db.execute(f"INSERT INTO runs(id,session_id,user_id,created,running,result) VALUES (?,?,{owner},?,0,?)",
                       (run_id, "seed-session", created, result))
    from finbridge.web_api import create_app
    with TestClient(create_app(database_path=admin_client.app.state.store.path)) as restarted:
        data = login_user(restarted, "admin", ADMIN_PASSWORD)
        headers = auth_headers(data["token"])
        ids = [r["id"] for r in restarted.get("/api/bootstrap", headers=headers).json()["runs"]]
        assert "FB-ORPHAN-HAITIAN-NEW" in ids, "海天应保留最新一条并归属 admin"
        assert "FB-OWN-HAITIAN" not in ids and "FB-ORPHAN-HAITIAN-OLD" not in ids, "admin 名下与无归属的海天重复记录应收敛"
        # 其他用户的同名企业记录不受影响
        with sqlite3.connect(restarted.app.state.store.path) as db:
            kept = db.execute("SELECT user_id FROM runs WHERE id='FB-USER02-HAITIAN'").fetchone()
            assert kept and kept[0] == db.execute("SELECT id FROM users WHERE username='user02'").fetchone()[0]
