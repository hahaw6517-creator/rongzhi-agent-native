import json
from copy import deepcopy

import httpx
import pytest

from finbridge.ai_insights import complete_text, generate_insight, evidence, InsightUnavailable
from finbridge.config import Settings


@pytest.mark.parametrize("model", ["deepseek-chat", "qwen-plus", "kimi-k2", "glm-4", "custom-model"])
def test_openai_provider_contract(model):
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "https://provider.test/v1/chat/completions"
        assert body["model"] == model
        assert body["messages"][0]["role"] == "system"
        assert "temperature" not in body and "tools" not in body and "response_format" not in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "企业现金重点。"}, "finish_reason": "stop"}]})
    assert complete_text(Settings("secret", "https://provider.test/v1", model), "专业指引", "企业证据", transport=httpx.MockTransport(handler)) == "企业现金重点。"


@pytest.mark.parametrize("base", ["https://provider.test", "https://provider.test/v1/"])
def test_anthropic_contract(base):
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "https://provider.test/v1/messages"
        assert request.headers["x-api-key"] == "secret"
        assert body["system"] == "专业指引"
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "重点分析"}], "stop_reason": "end_turn"})
    assert complete_text(Settings("secret", base, "claude", "anthropic"), "专业指引", "企业证据", transport=httpx.MockTransport(handler)) == "重点分析"


def test_reasoning_token_parameter_compatibility():
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": "use max_completion_tokens instead of max_tokens"})
        assert "max_tokens" not in body and body["max_completion_tokens"] == 4096
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>hidden</think>分析正文"}}]})
    assert complete_text(Settings("key", "https://provider.test", "reasoning"), "", "", transport=httpx.MockTransport(handler)) == "分析正文"
    assert len(calls) == 2


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (429, 2), (503, 2)])
def test_bounded_failures_do_not_leak_provider_response(status, attempts):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": "sensitive-key-secret"})
    with pytest.raises(InsightUnavailable) as exc:
        complete_text(Settings("secret", "https://provider.test", "m"), "", "", transport=httpx.MockTransport(handler))
    assert "secret" not in str(exc.value) and len(calls) == attempts


@pytest.mark.parametrize("choice", [{"message": {"content": None, "reasoning_content": "hidden"}}, {"message": {"content": "截断"}, "finish_reason": "length"}])
def test_empty_or_truncated_is_not_reported_as_success(choice):
    with pytest.raises(InsightUnavailable):
        complete_text(Settings("secret", "https://provider.test", "m"), "", "", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [choice]})))


def test_persisted_insights_are_cached_and_scoped_to_evidence():
    result = {"outputs": {"calculate_ratios": {"ratio": {"value": .5}}}, "input_profile": {"requested_amount": 3e8}}
    original = deepcopy(result); calls = []; states = []
    def sender(settings, system, context):
        calls.append(json.loads(context)); return "风险有依据。"
    settings = Settings("secret", "https://provider.test", "model")
    generate_insight(result, settings, "financial", sender=sender, progress=lambda: states.append(result["ai_insights"]["financial"]["status"]))
    restored = json.loads(json.dumps(result))
    generate_insight(restored, settings, "financial", sender=sender)
    assert len(calls) == 1 and states == ["running", "completed"]
    assert result["outputs"] == original["outputs"]
    restored["input_profile"]["requested_amount"] = 5e8
    generate_insight(restored, settings, "financial", sender=sender)
    assert len(calls) == 2 and calls[1]["request"]["requested_amount"] == 5e8
    assert "secret" not in json.dumps(restored)


def test_infeasible_risk_uses_failed_plan_and_verification(monkeypatch):
    plan = {"available": False, "decision_summary": "现金约束未通过", "composition": [], "cvar": {"value": 3}, "funding": {"unfunded_gap": 3e8}}
    monkeypatch.setattr("finbridge.market_rules.effective_portfolio", lambda _: plan)
    result = {"outputs": {"verify_decision": {"passed": False}}, "financial_analysis": {"available": False}}
    context = evidence(result, "risk")
    assert context["plan"]["available"] is False and context["verification"]["passed"] is False
    assert context["plan"]["composition"] == [] and context["plan"]["cvar"]["value"] == 3
    def sender(settings, system, content):
        assert "现金约束未通过" in content; return "先补足现金。"
    assert generate_insight(result, Settings("key", "url", "m"), "risk", sender=sender)["status"] == "completed"


def test_failed_section_does_not_block_other_section():
    result = {"outputs": {}}
    def fail(*args): raise RuntimeError("secret upstream data")
    settings = Settings("key", "url", "m")
    assert generate_insight(result, settings, "financial", sender=fail)["status"] == "unavailable"
    assert generate_insight(result, settings, "risk", sender=lambda *args: "风险分析")["status"] == "completed"
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("use_ai,protocol", [(True, "openai"), (True, "anthropic"), (False, "openai")])
def test_full_workflow_saves_both_sections_without_changing_calculations(monkeypatch, use_ai, protocol):
    from finbridge import web_api
    from finbridge.real_case import real_case
    from finbridge.workflow import DiligenceRun
    c = real_case()
    run = DiligenceRun(c["data"], c["profile"], "融资组合", "测试")
    calls = []; snapshots = []
    class Store:
        def save_progress(self, token, result, **kwargs):
            snapshots.append((deepcopy(result), kwargs))
    monkeypatch.setattr(web_api, "resolve_llm_settings", lambda *args: Settings("secret", "https://provider.test", "model", protocol))
    monkeypatch.setattr(web_api, "run_task_agent", lambda run, settings, progress: run.local(progress))
    def sender(settings, system, context):
        calls.append(json.loads(context)); return "基于当前企业的分析。"
    monkeypatch.setattr("finbridge.ai_insights.complete_text", sender)
    web_api._execute(Store(), "session", run, use_ai, 7)
    final, flags = snapshots[-1]
    assert final["status"] == "已完成" and flags == {"finished": True, "uid": 7}
    assert "prepare_deliverables" in final["outputs"]
    assert len(calls) == (2 if use_ai else 0)
    if use_ai:
        assert all(x["status"] == "completed" for x in final["ai_insights"].values())
        assert calls[0]["financial_analysis"]["available"]
        assert calls[1]["plan"]["composition"]
        assert any(r.get("ai_insights", {}).get("risk", {}).get("status") == "running" for r, _ in snapshots)
    assert "secret" not in json.dumps(final)
