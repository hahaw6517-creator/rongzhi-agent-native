from copy import deepcopy
import io
import json
from types import SimpleNamespace
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from finbridge.config import Settings
from finbridge.industry_context import SECTIONS, _rss_sources, analyze_industry_region
from finbridge.task_agent import run_task_agent
from finbridge.template import legacy_financial_template_xlsx as financial_template_xlsx
from finbridge.data import load_uploaded_financial_data
from finbridge.workflow import DiligenceRun, TOOLS, delivery_zip, report_html, report_markdown


@pytest.fixture
def engine():
    data = load_uploaded_financial_data("模拟.xlsx", financial_template_xlsx(True)).iloc[0].to_dict()
    profile = dict(amount=3e6, internal_funds=5e5, months=24, assumed_rate=.055,
                   purpose="经营周转", industry="精密制造", region="江苏苏州")
    return DiligenceRun(data, profile, "融资组合", "模拟数据")


def analysis_response(source_ids=None):
    return {"summary": "结合苏州精密制造企业回款与设备投入周期分析融资结构。", "funding_coverage_status": "unfunded",
            **{key: [{"title": title, "analysis": "结合应收占用安排经营融资，保留压力现金余量。",
                       "metric_keys": ["receivables_days"], "source_ids": source_ids or []}]
               for key, title in SECTIONS.items()}, "data_gaps": ["尚缺标准化同行融资样本"]}


def model_client(content):
    def create(**kwargs):
        message = SimpleNamespace(content=json.dumps(content, ensure_ascii=False))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def invoke(engine, content=None, search=None):
    outputs = engine.local()["outputs"]
    return analyze_industry_region(engine.data, engine.profile, outputs,
        client=model_client(content or analysis_response()), model="test-model", search=search or (lambda *_: []))


def test_industry_and_region_reach_model_with_calculated_metrics_but_no_credentials(engine):
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(analysis_response())))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    original = deepcopy((engine.data, engine.profile))
    outputs = engine.local()["outputs"]
    result = analyze_industry_region(engine.data, engine.profile, outputs, client=client, model="test", search=lambda *_: [])
    payload = json.loads(requests[0]["messages"][1]["content"])
    assert payload["region"] == "江苏苏州"
    assert payload["industry"] == "精密制造"
    assert payload["financial_metrics"]["receivables_days"]["value"] > 0
    assert payload["funding"]["debt_total"] == outputs["optimize_financing_portfolio"]["funding"]["debt_total"]
    assert "api_key" not in payload
    assert result["available"] and not result["peer_benchmark_available"]
    assert (engine.data, engine.profile) == original
    assert "非已核实" in result["sections"]["region"][0]["basis"]


def test_public_source_references_are_validated_and_preserved(engine):
    result = invoke(engine, analysis_response(["CTX-01"]), search=lambda *_: [
        {"title": "地方金融支持公开信息", "url": "https://www.suzhou.gov.cn/example",
         "snippet": "来源摘要，用于测试，不代表真实政策内容。", "published_at": "2025-01-01"}])
    assert result["available"]
    assert result["sources"][0]["id"] == "CTX-01"
    assert "摘要" in result["sections"]["region"][0]["basis"]
    assert "未核验全文" in result["sources"][0]["evidence_status"]


@pytest.mark.parametrize("mutation", [
    lambda x: x["region"][0].update(source_ids=["invented-source"]),
    lambda x: x["implications"][0].update(metric_keys=["invented_metric"]),
    lambda x: x.update(actions=[]),
    lambda x: x.update(summary=""),
    lambda x: x.update(funding_coverage_status="covered"),
    lambda x: x.update(summary="融资缺口可通过信用和抵押融资组合覆盖。"),
])
def test_invalid_model_schema_or_fabricated_references_fail_without_fake_analysis(engine, mutation):
    content = analysis_response()
    mutation(content)
    result = invoke(engine, content)
    assert not result["available"]
    assert result["status"] == "分析未完成"
    assert not any(result["sections"].values())


def test_missing_region_skips_search_and_model(engine):
    engine.profile["region"] = "未确认"
    def forbidden(*args, **kwargs):
        pytest.fail("Must not call external services without the required context")
    result = analyze_industry_region(engine.data, engine.profile, {}, client=None, model="test", search=forbidden)
    assert result["status"] == "待补充行业地区"


def test_search_failure_keeps_honest_model_only_analysis(engine):
    def unavailable(*_):
        raise RuntimeError("private search error")
    result = invoke(engine, search=unavailable)
    assert result["available"]
    assert not result["sources"]
    assert "仅作模型判断" in result["source_status"]
    assert "private search error" not in json.dumps(result)


def test_context_api_failure_does_not_block_financial_report_or_leak_provider_errors(engine):
    def fail(**kwargs):
        raise RuntimeError("private provider details and credentials")
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    engine.industry_analyzer = lambda d, p, out: analyze_industry_region(
        d, p, out, client=client, model="test", search=lambda *_: [])
    run = engine.local()
    context = run["outputs"]["analyze_industry_region"]
    assert run["status"] == "已完成"
    assert context["status"] == "分析未完成"
    assert context["failure_stage"] == "模型请求"
    assert run["outputs"]["optimize_financing_portfolio"]["available"]
    assert "private provider" not in json.dumps(run)
    assert "分析未完成" in report_html(run)


def test_model_text_is_escaped_in_export_and_server_anchor_keeps_unfunded_gap(engine):
    content = analysis_response()
    content["summary"] = '<script>alert("model")</script>'
    engine.industry_analyzer = lambda d, p, out: analyze_industry_region(
        d, p, out, client=model_client(content), model="test", search=lambda *_: [])
    run = engine.local()
    context = run["outputs"]["analyze_industry_region"]
    assert context["available"]
    assert context["funding_coverage_status"] == "unfunded"
    assert "0.001427亿元" in context["financial_anchor"]
    assert "<script>" not in report_html(run)


def test_public_search_ignores_nonprimary_and_private_links():
    xml = b'''<rss><channel>
      <item><title>Official</title><link>https://www.suzhou.gov.cn/test</link><description>Public excerpt</description></item>
      <item><title>Private</title><link>http://127.0.0.1/admin</link></item>
      <item><title>Untrusted</title><link>https://gov.cn.evil.test/x</link></item>
      <item><title>Credentials</title><link>https://user:pass@www.suzhou.gov.cn/x</link></item>
    </channel></rss>'''
    sources = _rss_sources(xml)
    assert len(sources) == 1
    assert sources[0]["published_at"] == "日期未提供"


def test_agent_executes_specialist_model_tool_and_exports_snapshot(engine):
    requests = []
    calls = [SimpleNamespace(id=f"call-{key}", function=SimpleNamespace(name=key, arguments="{}")) for key in TOOLS]
    planner_message = SimpleNamespace(tool_calls=calls, model_dump=lambda **_: {"role": "assistant", "content": None,
        "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": "{}"}} for c in calls]})
    def create(**kwargs):
        requests.append(kwargs)
        message = SimpleNamespace(content=json.dumps(analysis_response())) if "response_format" in kwargs else planner_message
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    run = run_task_agent(engine, Settings("fake", "https://example.invalid", "test"), client=client, source_search=lambda *_: [])
    assert run["mode"] == "AI 自主规划"
    assert len(requests) == 2  # One planner request and one real specialist-model interface call.
    assert run["outputs"]["analyze_industry_region"]["available"]
    assert len(run["events"]) == 9
    assert "同行融资观察" in report_markdown(run)
    assert "指标：应收账款周转天数" in report_markdown(run)
    assert "江苏苏州" in report_html(run)
    with zipfile.ZipFile(io.BytesIO(delivery_zip(run, run["outputs"]["prepare_deliverables"]["tasks"]))) as bundle:
        evidence = json.loads(bundle.read("evidence.json"))
        assert evidence["outputs"]["analyze_industry_region"]["summary"] == analysis_response()["summary"]


def test_local_workflow_never_calls_context_model_and_all_goals_finish(engine):
    for goal in ("融资组合", "风险分析", "方案比较"):
        run = DiligenceRun(engine.data, engine.profile, goal, "模拟数据").local()
        assert run["status"] == "已完成"
        assert run["outputs"]["analyze_industry_region"]["status"] == "未启用"
        assert len(run["events"]) == 9


def test_model_context_renders_on_financial_solution_and_report_pages(engine):
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    engine.industry_analyzer = lambda d, p, out: analyze_industry_region(
        d, p, out, client=model_client(analysis_response()), model="test", search=lambda *_: [])
    run = engine.local()
    app.session_state["runs"] = [run]
    app.session_state["active_run_id"] = run["id"]
    app.session_state["task_checklists"] = {run["id"]: run["outputs"]["prepare_deliverables"]["tasks"]}
    for page in ("execution", "solutions", "delivery"):
        app.switch_page(f"app_pages/{page}.py").run()
        assert not app.exception
        assert any(subheader.value == "行业与地区融资分析" for subheader in app.subheader)
