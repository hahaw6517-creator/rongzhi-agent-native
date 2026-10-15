from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from finbridge.industry_context import SECTIONS, analyze_industry_region
from finbridge.portfolio import build_financing_portfolio
from finbridge.template import SIMULATED_EXAMPLE
from finbridge.workflow import DiligenceRun, report_html, report_markdown


def make_run(goal, **updates):
    data=deepcopy(SIMULATED_EXAMPLE)
    data.update(updates)
    profile=dict(amount=500000., internal_funds=0., assumed_rate=.055, months=24,
                 purpose="经营周转", industry="精密制造", region="江苏苏州")
    return DiligenceRun(data,profile,goal,"测试虚构数据").local()


def focus(run):
    return run["outputs"]["prepare_deliverables"]["task_focus"]


def test_three_goals_produce_different_calculated_sections_and_reports():
    runs=[make_run(g) for g in ("融资组合","风险分析","方案比较")]
    assert "funding_steps" in focus(runs[0]) and "risk" not in focus(runs[0])
    assert "risk" in focus(runs[1]) and "comparison" not in focus(runs[1])
    assert "comparison" in focus(runs[2])
    assert len({report_markdown(r) for r in runs}) == 3
    for r in runs:
        assert "本次分析重点："+r["goal"] in report_html(r)
        assert r["status"] == "已完成" and len(r["events"]) == 9


def test_repayment_objective_changes_mix_at_same_coverage_and_lower_annual_burden():
    run=make_run("方案比较", confirmed_credit_limit=1e6, eligible_receivables=0,
        unencumbered_collateral_value=1e6, credit_rate=.03, credit_months=12,
        credit_fee_rate=0, secured_rate=.08, secured_months=60, secured_fee_rate=0)
    compare=focus(run)["comparison"]
    options={p["id"]:p for p in compare["options"]}
    base,repay=options["coverage"],options["repayment"]
    assert base["debt"] == repay["debt"] == 500000
    assert repay["new_service"] < base["new_service"]
    assert repay["total_cost"] > base["total_cost"]
    assert base["composition"] != repay["composition"]
    for p in options.values():
        assert p["feasible"] and p["common_stress_dscr"] >= 1.2
        assert all(c["used"] <= c["limit"]+.02 for c in p["constraints"])
    assert compare["duplicates"]  # The stronger buffer yields the same plan here; don't invent a third.


def test_stronger_stress_reduces_borrowing_without_changing_uploaded_limits():
    data=deepcopy(SIMULATED_EXAMPLE)
    profile=dict(amount=3e6,internal_funds=5e5,months=24,assumed_rate=.055,purpose="经营周转",industry="精密制造",region="苏州")
    original=deepcopy(data)
    run=DiligenceRun(data,profile,"方案比较","测试").local()
    options={p["id"]:p for p in focus(run)["comparison"]["options"]}
    assert options["buffer"]["debt"] < options["coverage"]["debt"]
    assert options["buffer"]["gap"] > options["coverage"]["gap"]
    assert data == original


def test_risk_cashflow_breakpoint_is_exact_for_selected_portfolio():
    run=make_run("风险分析")
    t=focus(run)["risk"]["threshold"]
    double=next(s for s in run["outputs"]["optimize_financing_portfolio"]["scenarios"] if s["id"]=="double")
    service=double["new_annual_service"]+double["existing_annual_service"]
    assert t["current_cfads"]*(1-t["cash_drop_limit"])/service == pytest.approx(t["target"])
    assert "营业收入" in t["note"] or "营收" in t["note"]


def test_risk_quantifies_cash_improvement_and_debt_reduction_as_alternatives():
    run=make_run("风险分析",cash_flow_available_for_debt_service=100000.)
    t=focus(run)["risk"]["threshold"]
    assert t["already_below"]
    assert t["cash_improvement"] == pytest.approx(800000)
    assert t["service_reduction"] == pytest.approx(600000-80000/1.2)


def test_zero_capacity_and_invalid_data_do_not_generate_fake_feasible_choices():
    zero=make_run("方案比较",confirmed_credit_limit=0,eligible_receivables=0,unencumbered_collateral_value=0)
    assert len(focus(zero)["comparison"]["options"]) == 1
    assert focus(zero)["comparison"]["options"][0]["debt"] == 0
    invalid=make_run("方案比较",total_assets=1)
    assert focus(invalid)["comparison"]["options"] == []
    assert not focus(invalid)["available"]


def test_api_receives_goal_and_server_computed_risk_in_plain_language_prompt():
    run=make_run("风险分析")
    captured=[]
    parsed=dict(summary="先看回款和还款安排。",funding_coverage_status="covered",data_gaps=[])
    parsed.update({k:[dict(title="本次重点",analysis="先核对回款，再安排还款。",metric_keys=[],source_ids=[])] for k in SECTIONS})
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    context=analyze_industry_region(run["data"],run["profile"],run["outputs"],client=client,model="test",search=lambda *_:[],goal="风险分析")
    assert context["available"]
    payload=json.loads(captured[0]["messages"][1]["content"])
    assert payload["analysis_goal"] == "风险分析"
    assert payload["calculated_task_focus"]["risk"]["threshold"]["cash_drop_limit"] is not None
    assert "大白话" in captured[0]["messages"][0]["content"]


@pytest.mark.parametrize("goal,title",[("风险分析","先看哪里最容易出问题"),("方案比较","把几种借法放在一起比较")])
def test_goal_specific_result_is_visible_on_portfolio_and_report_pages(goal,title):
    from streamlit.testing.v1 import AppTest
    run=make_run(goal)
    app=AppTest.from_file("../app.py",default_timeout=20).run()
    app.session_state["runs"]=[run]
    app.session_state["active_run_id"]=run["id"]
    app.session_state["task_checklists"]={run["id"]:run["outputs"]["prepare_deliverables"]["tasks"]}
    for page in ("solutions","delivery"):
        app.switch_page(f"app_pages/{page}.py").run()
        assert not app.exception
        assert any(s.value==title for s in app.subheader)
