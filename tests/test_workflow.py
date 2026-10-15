from copy import deepcopy
import io
import json
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from finbridge.config import Settings
from finbridge.task_agent import run_task_agent
from finbridge.workflow import DiligenceRun, TOOLS, check_data, delivery_zip, fingerprint, report_html, simulate_repayment


@pytest.fixture
def inputs():
    data = pd.read_csv("data/demo_diligence.csv").iloc[0].to_dict()
    profile = dict(amount=3e6, internal_funds=5e5, months=24, assumed_rate=.055, purpose="经营周转", collateral="未确认", receivables="可提供")
    return data, profile


def test_diligence_generates_evidence_routes_actions_and_real_trace(inputs):
    data, profile = inputs
    run = DiligenceRun(data, profile, "融资准备", "模拟数据").local()
    assert run["status"] == "已完成"
    assert len(run["events"]) == len(TOOLS)
    assert "optimize_financing_portfolio" in run["outputs"]
    assert run["outputs"]["optimize_financing_portfolio"]["composition"]
    assert len(run["outputs"]["calculate_ratios"]) == 36
    assert run["outputs"]["simulate_repayment"]["gap"] == 2.5e6
    assert run["outputs"]["prepare_deliverables"]["tasks"]
    assert all(e["status"] == "完成" for e in run["events"])
    assert run["outputs"]["calculate_ratios"]["debt_to_asset_ratio"]["value"] == pytest.approx(.45)


def test_missing_cfads_never_substitutes_profit(inputs):
    data, profile = inputs
    data.pop("cash_flow_available_for_debt_service")
    result = DiligenceRun(data, profile, "融资准备", "用户数据").local()
    assert not result["outputs"]["simulate_repayment"]["available"]
    assert all(s["dscr"] is None for s in result["outputs"]["simulate_repayment"]["scenarios"])
    assert result["outputs"]["prepare_deliverables"]["readiness"] == "待补充关键资料"
    assert any("CFADS" in t["title"] for t in result["outputs"]["prepare_deliverables"]["tasks"])


def test_data_contradictions_block_stress_test(inputs):
    data, profile = inputs
    data["current_assets"] = data["total_assets"] + 1
    result = DiligenceRun(data, profile, "风险排查", "用户数据").local()
    assert result["outputs"]["inspect_data"]["blocked"]
    assert result["outputs"]["simulate_repayment"]["scenarios"] == []
    assert result["outputs"]["prepare_deliverables"]["readiness"] == "数据待修正"


def test_conflicting_debt_schedule_blocks_extra_leverage(inputs):
    data, profile = inputs
    data.update(scheduled_debt_service=0, annual_principal_repayment=1_000_000, annual_interest_payment=100_000, confirmed_credit_limit=3_000_000)
    run = DiligenceRun(data, profile, "融资组合", "用户上传").local()
    assert run["outputs"]["inspect_data"]["blocked"]
    assert not run["outputs"]["optimize_financing_portfolio"]["available"]
    assert run["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"] is None


@pytest.mark.parametrize("debts", [(4_000_000, 2_000_000, 1_000_000), (2_600_000, 0, 1_000_000)])
def test_debt_components_cannot_exceed_statement_totals(inputs, debts):
    data, _ = inputs
    data.update(zip(("short_term_debt", "long_term_debt", "current_portion_long_term_debt"), debts))
    assert check_data(data)["blocked"]


@pytest.mark.parametrize("debt", [{"annual_principal_repayment": 1_500_000}, {"annual_interest_payment": 100_000}])
def test_missing_other_debt_component_cannot_erase_known_payment(inputs, debt):
    data, profile = inputs
    data.update(scheduled_debt_service=0, **debt)
    result = DiligenceRun(data, profile, "融资组合", "用户上传").local()
    assert result["outputs"]["inspect_data"]["blocked"]
    assert not result["outputs"]["optimize_financing_portfolio"]["available"]


def test_partially_filled_debt_balance_is_still_bounded(inputs):
    data, _ = inputs
    data.update(short_term_debt=data["total_liabilities"]+100)
    assert check_data(data)["blocked"]


def test_internal_funding_requires_cash_or_confirmed_independent_source(inputs):
    data, profile = inputs
    data.update(cash_and_equivalents=500_000, restricted_cash=100_000, minimum_cash_reserve=300_000)
    profile.update(amount=2_000_000, internal_funds=2_000_000)
    blocked = DiligenceRun(data, profile, "融资组合", "用户上传").local()
    assert blocked["outputs"]["inspect_data"]["blocked"]
    data["confirmed_additional_internal_funds"] = 1_900_000
    valid = DiligenceRun(data, profile, "融资组合", "用户上传").local()
    assert not valid["outputs"]["inspect_data"]["blocked"]
    assert valid["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"] == 0


@pytest.mark.parametrize("value", [True, float('inf'), -2, 'not a number'])
def test_invalid_assets_are_not_silently_accepted(inputs, value):
    data, _ = inputs
    data["total_assets"] = value
    assert "total_assets" in check_data(data)["invalid"]


def test_equipment_purpose_excludes_working_capital(inputs):
    data, profile = inputs
    profile["purpose"] = "设备购置"
    routes = DiligenceRun(data, profile, "方案比较", "模拟数据").local()["outputs"]["match_routes"]
    assert routes[0]["id"] == "leasing"
    assert next(x for x in routes if x["id"] == "working")["status"] == "用途不符"


def test_stress_test_accounts_for_existing_debt_and_rates(inputs):
    data, profile = inputs
    baseline = simulate_repayment(data, profile)
    a, b, c, d = baseline["scenarios"]
    assert a["total_annual_service"] == a["new_annual_service"] + data["scheduled_debt_service"]
    assert b["dscr"] < a["dscr"]
    assert c["new_annual_service"] > a["new_annual_service"]
    assert d["dscr"] < min(b["dscr"], c["dscr"])
    zero = simulate_repayment(data, dict(profile, assumed_rate=0))["scenarios"][0]
    assert zero["new_annual_service"] == pytest.approx(2.5e6/24*12)


def test_negative_cfads_deteriorates_under_stress(inputs):
    data, profile = inputs
    data["cash_flow_available_for_debt_service"] = -100
    result = simulate_repayment(data, profile)
    assert result["scenarios"][1]["cfads"] < result["scenarios"][0]["cfads"]


def test_tiny_rates_and_short_tenors_do_not_crash_or_assume_rollover(inputs):
    data, profile = inputs
    result = simulate_repayment(data, dict(profile, assumed_rate=1e-16, months=3))
    assert result["scenarios"][0]["new_annual_service"] == pytest.approx(2_500_000)
    assert all(s["new_annual_service"] > 0 for s in result["scenarios"])


def test_quarterly_cashflow_not_used_as_annual_cfads(inputs):
    data, profile = inputs
    data["report_period"] = "2025年第一季度"
    assert not simulate_repayment(data, profile)["available"]


def test_dependencies_and_arbitrary_tools_cannot_be_bypassed(inputs):
    run = DiligenceRun(*inputs, "融资准备", "模拟数据")
    assert "error" in run.execute("prepare_deliverables")
    assert "error" in run.execute("shell_command")
    assert "error" in run.execute("inspect_data", {"total_assets": 1})
    assert not run.result["outputs"]


def test_snapshot_is_immutable_and_detects_profile_change(inputs):
    data, profile = inputs
    original = deepcopy(data)
    run = DiligenceRun(data, profile, "融资准备", "模拟数据").local()
    data["total_assets"] = 1
    assert run["data"]["total_assets"] == original["total_assets"]
    assert run["fingerprint"] != fingerprint(data, profile)
    profile["months"] = 36
    assert run["fingerprint"] != fingerprint(original, profile)


def test_export_is_complete_and_escapes_source_text(inputs):
    data, profile = inputs
    data["company_name"] = '<script>alert(1)</script>'
    run = DiligenceRun(data, profile, "融资准备", "用户数据").local()
    assert '<script>' not in report_html(run)
    assert "定量融资组合" in report_html(run)
    assert "旧版快照" not in report_html(run)
    tasks = deepcopy(run["outputs"]["prepare_deliverables"]["tasks"])
    tasks[0]["completed"] = True
    with zipfile.ZipFile(io.BytesIO(delivery_zip(run, tasks))) as z:
        assert set(z.namelist()) == {"report.md", "report.html", "evidence.json", "action-checklist.csv", "delivery-status.json"}
        assert json.loads(z.read("evidence.json"))["id"] == run["id"]
        assert "True" in z.read("action-checklist.csv").decode("utf-8-sig")


class Message:
    def __init__(self, tools):
        self.tool_calls = [SimpleNamespace(id=f"call-{i}-{name}", function=SimpleNamespace(name=name, arguments="{}")) for i, name in enumerate(tools)]
    def model_dump(self, **kwargs):
        return {"role": "assistant", "content": None, "tool_calls": [{"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}} for t in self.tool_calls]}


def test_model_planner_observes_error_then_recovers(inputs):
    responses = iter([Message(["prepare_deliverables"]), Message(list(TOOLS))])
    calls = []
    def create(**kwargs):
        calls.append(deepcopy(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=next(responses))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    run = run_task_agent(DiligenceRun(*inputs, "融资准备", "模拟数据"), Settings("fake", "https://example.invalid", "test"), client=client, source_search=lambda *_: [])
    assert run["status"] == "已完成"
    assert run["mode"] == "AI 自主规划"
    assert run["events"][0]["status"] == "失败"
    assert any(m["role"] == "tool" and "依赖" in m["content"] for m in calls[1]["messages"])


def test_model_failure_falls_back_with_honest_mode(inputs):
    def fail(**kwargs):
        raise RuntimeError("private provider details")
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    run = run_task_agent(DiligenceRun(*inputs, "风险排查", "模拟数据"), Settings("fake", "https://example.invalid", "test"), client=client)
    assert run["mode"] == "AI 中断 · 本地续跑"
    assert run["status"] == "已完成"
    assert "private provider details" not in json.dumps(run)
