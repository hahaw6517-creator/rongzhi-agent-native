"""Integration checks for the independent website, without paid model calls."""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest
from starlette.testclient import TestClient

from finbridge.config import Settings
from finbridge import web_api
from conftest import settle


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings(None, "https://api.example.test", "test-model"))
    # This suite retains the historical API contract. Public-mode integration is
    # exercised separately in test_public_api.py with the production defaults.
    from finbridge.template import legacy_financial_template_xlsx,legacy_financial_template_csv
    from finbridge.data import load_uploaded_financial_data
    import pandas as pd
    first=load_uploaded_financial_data("历史.xlsx",legacy_financial_template_xlsx(True)).iloc[0].to_dict()
    demos=[web_api.clean_data(first),*[web_api.clean_data(r) for r in pd.read_csv(web_api.ROOT/"data/demo_diligence.csv").iloc[1:].to_dict("records")]]
    monkeypatch.setattr(web_api,"_read_demos",lambda:demos)
    monkeypatch.setattr(web_api,"financial_template_xlsx",legacy_financial_template_xlsx)
    monkeypatch.setattr(web_api,"financial_template_csv",legacy_financial_template_csv)

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<!doctype html><title>融智</title><script src="/app.js"></script>', encoding="utf-8")
    (web / "app.js").write_text("'use strict';", encoding="utf-8")
    return web_api.create_app(database_path=tmp_path / "runtime.sqlite3", web_root=web)


@pytest.fixture
def client(app):
    with TestClient(app) as browser:
        yield browser


def test_adjustment_endpoint_preserves_task_and_checks_permitted_fields(client):
    run=finish(client,goal="风险分析")
    before=client.get("/api/runs/"+run["id"]).json()
    response=client.post("/api/runs/"+run["id"]+"/adjustment",json={"changes":{"cash_flow_available_for_debt_service":100000}})
    assert response.status_code==200,response.text
    assert response.json()["focus"]["risk"]["threshold"]["cash_improvement"]>0
    assert client.get("/api/runs/"+run["id"]).json()==before
    bad=client.post("/api/runs/"+run["id"]+"/adjustment",json={"changes":{"total_assets":1}})
    assert bad.status_code==400


def finish(client, *, goal="融资准备", profile=None, use_ai=False):
    response = client.post("/api/runs", json={"goal": goal, "profile": profile or {}, "use_ai": use_ai})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    for _ in range(200):
        run = client.get("/api/runs/" + run_id).json()
        if run["status"] != "执行中":
            assert run["status"] == "已完成", run
            return run
        time.sleep(0.005)
    pytest.fail("Local task did not complete")


def test_bootstrap_cookie_and_native_static(client):
    static = client.get("/")
    assert static.status_code == 200
    assert "streamlit" not in static.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/.env").status_code == 404
    response = client.get("/api/bootstrap")
    value = response.json()
    assert value["data"]["company_name"].startswith("华辰")
    assert value["model_configured"] is False
    assert len(value["tools"]) == len(web_api.TOOLS)
    assert len(value["cases"]) == 3
    assert value["runs"] == []
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert "api_key" not in response.text
    assert "base_url" not in response.text


def test_known_client_pages_support_refresh_without_api_fallback(client):
    for path in ("/company", "/execution", "/solutions", "/delivery", "/knowledge"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "text/html" in response.headers["content-type"]
        assert '<script src="/app.js">' in response.text
    for path in ("/unknown-page", "/api/unknown", "/api/runs/unknown/download"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]
        assert "<script" not in response.text


def test_new_session_derives_funding_profile_from_default_case(client, monkeypatch):
    cases = web_api._read_demos()
    cases[0].update(company_name="新默认案例（模拟）", financing_need=880_000,
                    available_internal_funds=30_000, purpose="综合融资",
                    credit_rate=.041, credit_months=60)
    monkeypatch.setattr(web_api, "_read_demos", lambda: deepcopy(cases))
    state = client.get("/api/bootstrap").json()
    assert state["profile"]["amount"] == 880_000
    assert state["profile"]["internal_funds"] == 30_000
    assert state["profile"]["purpose"] == "综合融资"
    assert state["profile"]["months"] == web_api.DEFAULT_PROFILE["months"]
    assert state["profile"]["assumed_rate"] == web_api.DEFAULT_PROFILE["assumed_rate"]
    assert state["data"]["credit_months"] == 60
    assert state["data"]["credit_rate"] == .041
    assert "新默认案例" in state["source"]


def test_demo_atomically_replaces_funding_inputs_and_preserves_channel_parameters(client, monkeypatch):
    previous = client.get("/api/bootstrap").json()
    profile = dict(previous["profile"], amount=9_000_000, internal_funds=2_000_000,
                   months=18, assumed_rate=.09, purpose="设备购置")
    assert client.post("/api/company", json={"data": previous["data"], "profile": profile}).status_code == 200
    cases = web_api._read_demos()
    cases[0].update(financing_need=880_000, available_internal_funds=30_000,
                    purpose="综合融资", credit_rate=.041, credit_months=60)
    monkeypatch.setattr(web_api, "_read_demos", lambda: deepcopy(cases))
    response = client.post("/api/demo", json={"id": "0"})
    assert response.status_code == 200
    state = response.json()
    # 案例只载入数据，融资需求由用户确认后再手动启动。
    assert state["active_run_id"] is None
    assert state["runs"] == []
    assert state["profile"]["amount"] == 880_000
    assert state["profile"]["internal_funds"] == 30_000
    assert state["profile"]["purpose"] == "综合融资"
    assert state["profile"]["months"] == 18
    assert state["profile"]["assumed_rate"] == .09
    assert state["data"]["credit_rate"] == .041
    assert state["data"]["credit_months"] == 60
    persisted = client.get("/api/bootstrap").json()
    assert persisted["data"] == state["data"]
    assert persisted["profile"] == state["profile"]
    cases[1].pop("financing_need")
    cases[1].pop("available_internal_funds")
    cases[1].pop("purpose", None)
    state = client.post("/api/demo", json={"id": "1"}).json()
    assert state["profile"]["amount"] == 0
    assert state["profile"]["internal_funds"] == 0
    assert state["profile"]["purpose"] == "经营周转"


def test_browser_sessions_cannot_read_or_change_other_tasks(app):
    with TestClient(app) as first, TestClient(app) as second:
        state = first.get("/api/bootstrap").json()
        data = dict(state["data"], company_name="仅第一个浏览器可见")
        assert first.post("/api/company", json={"data": data}).status_code == 200
        run = finish(first)
        assert second.get("/api/bootstrap").json()["data"]["company_name"] != data["company_name"]
        for suffix in ("", "/download?format=json"):
            assert second.get("/api/runs/" + run["id"] + suffix).status_code == 404
        assert second.patch("/api/runs/" + run["id"], json={"reviewed": True}).status_code == 404
        assert second.post("/api/runs/" + run["id"] + "/simulate", json={}).status_code == 404


def test_local_task_preserves_locked_snapshot_and_exposes_evidence(client):
    before = client.get("/api/bootstrap").json()
    run = finish(client, profile={"objective": "检查偿付能力", "months": 36})
    assert len(run["events"]) == len(web_api.TOOLS)
    assert run["outputs"]["optimize_financing_portfolio"]["composition"]
    assert all(event["status"] == "完成" for event in run["events"])
    assert len(run["outputs"]["calculate_ratios"]) == 36
    assert run["tasks"]
    assert not run["stale"]
    changed = deepcopy(before["data"])
    changed.update(company_name="修订企业", revenue=111_000_000)
    client.post("/api/company", json={"data": changed})
    historical = client.get("/api/runs/" + run["id"]).json()
    assert historical["stale"]
    assert historical["data"]["revenue"] == before["data"]["revenue"]
    assert historical["profile"]["months"] == 36


def test_delivery_updates_progress_without_rewriting_report(client):
    run = finish(client)
    url = "/api/runs/" + run["id"]
    response = client.patch(url, json={"reviewed": True, "tasks": [{"id": run["tasks"][0]["id"], "completed": True}]})
    assert response.status_code == 200
    updated = response.json()
    assert updated["reviewed"]
    assert updated["tasks"][0]["completed"]
    assert not updated["outputs"]["prepare_deliverables"]["tasks"][0]["completed"]
    package = client.get(url + "/download?format=zip")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        status = json.loads(archive.read("delivery-status.json"))
        assert status["completed_actions"] == 1
        assert status["reviewed_in_session"]
        assert "True" in archive.read("action-checklist.csv").decode("utf-8-sig")
    for extension in ("html", "markdown", "json", "csv"):
        response = client.get(url + "/download?format=" + extension)
        assert response.status_code == 200
        assert "attachment;" in response.headers["content-disposition"]
    assert client.get(url + "/download?format=exe").status_code == 400
    assert client.patch(url, json={"tasks": [{"id": "fake", "completed": True}]}).status_code == 400
    assert client.patch(url, json={"reviewed": "yes"}).status_code == 400


def test_scenario_changes_do_not_mutate_task(client):
    run = finish(client, profile={"amount": 20_000_000})
    url = "/api/runs/" + run["id"]
    simulation = client.post(url + "/simulate", json={"assumed_rate": 0.08, "cash_drop": 0.4, "rate_up": 0.02}).json()
    assert simulation["available"]
    assert len(simulation["scenarios"]) == 4
    assert simulation["scenarios"][0]["assumed_rate"] == 0.08
    assert simulation["scope"] == "original_request"
    assert simulation["basis"]["gap"] == simulation["gap"] == 19_500_000
    assert simulation["basis"]["assumed_rate"] == 0.08
    assert simulation["basis"]["months"] == run["profile"]["months"]
    assert simulation["basis"]["repayment_structure"] == "统一等额本息"
    assert simulation["gap"] != run["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"]
    unchanged = client.get(url).json()
    assert unchanged["profile"] == run["profile"]
    assert unchanged["data"] == run["data"]
    assert unchanged["outputs"] == run["outputs"]
    assert unchanged["fingerprint"] == run["fingerprint"]
    assert client.post(url + "/simulate", json={"cash_drop": 1.1}).status_code == 400
    assert client.post(url + "/simulate", json={"assumed_rate": True}).status_code == 400


def test_demo_cases_and_incomplete_data_remain_truthful(client):
    response = client.post("/api/demo", json={"id": "2"})
    assert response.status_code == 200
    assert response.json()["quality"]["coverage"] < 100
    assert response.json()["profile"]["receivables"] == "未确认"
    assert response.json()["active_run_id"] is None
    run = finish(client, goal="风险排查")
    assert not run["outputs"]["simulate_repayment"]["available"]
    assert run["outputs"]["calculate_ratios"]["dscr"]["value"] is None
    assert run["outputs"]["prepare_deliverables"]["tasks"]
    assert client.post("/api/demo", json={"id": "no-such-case"}).status_code == 400


def test_upload_parse_then_explicit_selection(client):
    initial = client.get("/api/bootstrap").json()
    content = "企业名称,报告期,资产总额（万元）,负债总额（万元）,营业收入（万元）,净利润（万元）\n上传企业,2025年度,1000,300,500,30\n".encode()
    response = client.post("/api/upload", files={"file": ("financial.csv", content, "text/csv")})
    assert response.status_code == 200, response.text
    row = response.json()["records"][0]
    assert row["total_assets"] == 10_000_000
    assert row["company_name"] == "上传企业"
    assert client.get("/api/bootstrap").json()["data"] == initial["data"]
    result = client.post("/api/company", json={"data": row, "source": "用户上传 · financial.csv"})
    assert result.status_code == 200
    assert result.json()["data"]["company_name"] == "上传企业"
    template = client.get("/api/template?legacy=1")
    assert template.status_code == 200
    assert template.content.startswith(b"PK")
    chinese_csv = client.get("/api/template?format=csv&legacy=1").content.decode("utf-8-sig")
    assert "企业名称" in chinese_csv
    assert "合格可融资应收账款" in chinese_csv


def test_chinese_example_upload_to_financing_portfolio_and_report(client):
    initial = client.get("/api/bootstrap").json()
    template = client.get("/api/template?example=1&legacy=1")
    upload = client.post("/api/upload", files={"file": ("中文融资示例.xlsx", template.content)})
    assert upload.status_code == 200, upload.text
    row = upload.json()["records"][0]
    assert row["credit_rate"] == pytest.approx(.052)
    assert row["credit_months"] == 24
    profile = dict(initial["profile"], amount=row["financing_need"],
                   internal_funds=row["available_internal_funds"],
                   purpose=row["purpose"], industry=row["industry"], region=row["region"])
    response = client.post("/api/company", json={"data": row, "profile": profile, "source": "用户上传 · 中文融资示例.xlsx"})
    assert response.status_code == 200
    assert response.json()["profile"]["amount"] == row["financing_need"]
    run = finish(client, goal="融资组合")
    plan = run["outputs"]["optimize_financing_portfolio"]
    assert plan["available"]
    assert plan["funding"]["gap"] == row["financing_need"] - row["available_internal_funds"]
    assert len(plan["scenarios"]) == 5
    assert sum(channel["amount"] for channel in plan["composition"]) == pytest.approx(plan["funding"]["debt_total"])
    report = client.get("/api/runs/" + run["id"] + "/download?format=markdown")
    assert report.status_code == 200
    assert "定量融资组合" in report.text
    assert "融资组合压力测试" in report.text
    assert "原始融资请求的偿付压力测试" in report.text
    package = client.get("/api/runs/" + run["id"] + "/download?format=zip")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert archive.read("report.md").decode("utf-8") == report.text
        assert "融资组合与压力测试概览" in archive.read("report.html").decode("utf-8")


def test_legacy_snapshot_without_portfolio_remains_downloadable(client, app):
    run = finish(client)
    legacy = deepcopy(run)
    legacy["outputs"].pop("optimize_financing_portfolio")
    with app.state.store.connect() as db:
        db.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(legacy, ensure_ascii=False), run["id"]))
    url = "/api/runs/" + run["id"]
    assert "optimize_financing_portfolio" not in client.get(url).json()["outputs"]
    for mode in ("markdown", "html"):
        response = client.get(url + "/download?format=" + mode)
        assert response.status_code == 200
        assert "此历史结果尚未计算融资组合，请重新生成分析" in response.text
    package = client.get(url + "/download?format=zip")
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert "此历史结果尚未计算融资组合" in archive.read("report.md").decode("utf-8")


@pytest.mark.parametrize("name,content", [("report.pdf", b"%PDF-1.4"), ("bad.csv", b"not,a,financial,table\n"), ("bad.xlsx", b"not-a-zip-file"), ("empty.csv", b"")])
def test_malformed_uploads_return_chinese_errors(client, name, content):
    response = client.post("/api/upload", files={"file": (name, content)})
    assert response.status_code == 400
    assert "error" in response.json()
    assert "Traceback" not in response.text


def test_large_uploads_rejected_before_parsing(client):
    response = client.post("/api/upload", files={"file": ("large.csv", b"x" * (web_api.MAX_FILE_BYTES + 1))})
    assert response.status_code == 413
    assert "10MB" in response.json()["error"]


def test_same_origin_writes_and_json_validation(client):
    assert client.post("/api/demo", json={"id": "0"}, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/demo", json={"id": "0"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/demo", json={"id": "0"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/runs", json={"profile": {"amount": True}}).status_code == 400
    assert client.post("/api/runs", json={"profile": {"months": 12.5}}).status_code == 400
    assert client.post("/api/runs", json={"profile": {"purpose": []}}).status_code == 400
    assert client.post("/api/runs", json={"profile": {"api_key": "not-allowed"}}).status_code == 400
    assert client.post("/api/runs", json={"use_ai": "yes"}).status_code == 400
    assert client.post("/api/runs", content='{"profile":{"amount":NaN}}', headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/api/runs", content="not json").status_code == 415
    assert client.post("/api/runs", json={"use_ai": True}).status_code == 400
    assert client.post("/api/company", json={"data": {"company_name": ""}}).status_code == 400


def test_ai_execution_uses_existing_planner_without_revealing_credentials(client, monkeypatch):
    monkeypatch.setattr("finbridge.ai_insights.complete_text", lambda *args: "模型测试解读。")
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings("secret-never-return", "https://api.example.test", "test-model"))
    def mock_agent(run, settings, progress):
        assert settings.api_key == "secret-never-return"
        run.result["mode"] = "AI 自主规划"
        return run.local(progress)
    monkeypatch.setattr(web_api, "run_task_agent", mock_agent)
    run = finish(client, use_ai=True)
    assert run["mode"] == "AI 自主规划"
    assert {k: v["status"] for k, v in run["ai_insights"].items()} == {"financial": "completed", "risk": "completed"}
    # Reloading a stored report must never invoke the model again.
    def unexpected_call(*args):
        pytest.fail("Report refresh triggered a paid call")
    monkeypatch.setattr("finbridge.ai_insights.complete_text", unexpected_call)
    for _ in range(3):
        assert client.get('/api/runs/' + run['id']).json()['ai_insights'] == run['ai_insights']
    assert "secret-never-return" not in json.dumps(run)
    assert client.get("/api/bootstrap").json()["model_configured"] is True


def test_result_questions_require_consent_and_use_task_snapshot(client, monkeypatch):
    run = finish(client)
    url = "/api/runs/" + run["id"] + "/question"
    assert client.post(url, json={"question": "解释风险"}).status_code == 400
    assert client.post(url, json={"question": "解释风险", "consent": True}).status_code == 400
    monkeypatch.setattr("finbridge.model_resolver.load_settings", lambda: Settings("secret", "https://api.example.test", "model"))
    class MockAgent:
        def __init__(self, settings):
            assert settings.api_key == "secret"
        def chat(self, history, data):
            assert run["id"] in history[0]["content"]
            assert data == run["data"]
            return "依据本任务快照，需核验现金流。"
    monkeypatch.setattr(web_api, "FinancialAgent", MockAgent)
    response = client.post(url, json={"question": "解释风险", "consent": True})
    assert response.status_code == 200
    assert "快照" in response.json()["answer"]


def test_running_task_exposes_progress_and_prevents_duplicate_execution(client, monkeypatch):
    paused, release = threading.Event(), threading.Event()
    original = web_api.DiligenceRun.local
    def slow_local(run, progress):
        run.execute("inspect_data")
        progress(run.result["events"][-1])
        paused.set()
        assert release.wait(5)
        return original(run, progress)
    monkeypatch.setattr(web_api.DiligenceRun, "local", slow_local)
    try:
        started = client.post("/api/runs", json={})
        assert started.status_code == 202
        assert paused.wait(3)
        run = client.get("/api/runs/" + started.json()["id"]).json()
        assert run["status"] == "执行中"
        assert run["events"][0]["tool"] == "inspect_data"
        assert client.post("/api/runs", json={}).status_code == 409
        assert client.get("/api/runs/" + run["id"] + "/download").status_code == 409
    finally:
        release.set()


def test_sqlite_persistence_and_history_limit(app, client):
    first = finish(client)
    for _ in range(web_api.MAX_RUNS):
        finish(client)
    state = client.get("/api/bootstrap").json()
    assert len(state["runs"]) == web_api.MAX_RUNS
    assert first["id"] not in [run["id"] for run in state["runs"]]
    assert client.get("/api/runs/" + first["id"]).status_code == 404
    saved_token = client.cookies[web_api.COOKIE]
    restarted = web_api.create_app(database_path=app.state.store.path, web_root=Path("web"))
    with TestClient(restarted) as after_restart:
        after_restart.cookies.set(web_api.COOKIE, saved_token)
        assert after_restart.get("/api/bootstrap").json()["runs"][0]["id"] == state["runs"][0]["id"]
