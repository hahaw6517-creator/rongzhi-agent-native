from copy import deepcopy
from io import BytesIO
import pytest
from finbridge.public_data import public_example,PUBLIC_KEYS,BLOCKS
from finbridge.public_finance import public_model
from finbridge.public_portfolio import verify_public_plan
from finbridge.workflow import DiligenceRun,report_markdown,report_html
from finbridge.data import load_uploaded_financial_data
from finbridge.public_template import public_template_xlsx,public_template_csv


@pytest.mark.parametrize("goal",["融资组合","风险分析","方案比较"])
def test_public_pipeline_needs_no_private_inputs_and_verifies_math(goal):
    raw=public_example();before=deepcopy(raw)
    run=DiligenceRun(raw,{},goal,"模拟公开格式").local()
    assert raw==before and run["status"]=="已完成"
    assert len(run["events"])==11 and all(e["status"]=="完成" for e in run["events"])
    assert {"estimate_financing_need","verify_decision"}<=run["outputs"].keys()
    assert len(run["outputs"]["simulate_repayment"]["scenarios"])==4
    assert len(run["outputs"]["match_routes"])==4
    plan=run["outputs"]["optimize_financing_portfolio"]
    assert plan["available"] and plan["public_basis"]
    assert plan["funding"]["debt_total"]>0
    assert run["outputs"]["verify_decision"]["passed"]
    assert "dscr" not in run["outputs"]["calculate_ratios"]
    report=report_markdown(run)
    assert "情景假设" in report and "公开输入与来源" in report and "自主推导" in report
    assert "公开财务报表融资决策报告" in report_html(run)


def test_absent_public_values_are_not_zero_and_private_values_cannot_poison_decision():
    raw=public_example()
    clean=public_model(raw)
    poisoned=dict(raw,confirmed_credit_limit=1e15,eligible_receivables=1e15,cash_flow_available_for_debt_service=1e15,financing_need=1e15)
    assert public_model(poisoned)==clean
    missing=public_model(dict(raw,capital_expenditure=None))
    assert not missing["available"] and "capital_expenditure" in missing["missing"]


def test_verifier_detects_modified_allocations_independently():
    run=DiligenceRun(public_example(),{},"融资组合","模拟").local()
    p=deepcopy(run["outputs"]["optimize_financing_portfolio"])
    p["composition"][0]["amount"]+=1e8
    assert not verify_public_plan(p)["passed"]


@pytest.mark.parametrize("extension,content",[("xlsx",lambda:public_template_xlsx(True)),("csv",lambda:public_template_csv(True))])
def test_public_block_template_roundtrip_and_provenance(extension,content):
    frame=load_uploaded_financial_data("公开报表."+extension,content())
    row=frame.iloc[0].to_dict()
    assert set(row)<=PUBLIC_KEYS
    assert row["revenue"]==public_example()["revenue"]
    assert row["accounts_receivable"]==public_example()["accounts_receivable"]
    assert row["public_provenance"]["revenue"]["cell"].startswith("C")
    assert public_model(row)["available"]


def test_higher_capex_or_stress_changes_budget_without_changing_raw_statements():
    raw=public_example()
    a=DiligenceRun(raw,{},"融资组合","模拟").local()
    b=DiligenceRun(raw,{"capex_multiplier":1.5,"cash_drop":.3},"融资组合","模拟").local()
    assert a["raw_public"]==b["raw_public"]
    assert b["public_analysis"]["gap"]>a["public_analysis"]["gap"]
    assert b["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"]<=a["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"]


@pytest.mark.parametrize("goal",["融资组合","风险分析","方案比较"])
def test_public_pages_and_saved_revisions(goal):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file("../app.py",default_timeout=25).run()
    assert not app.exception
    app.segmented_control[0].set_value(goal)
    next(b for b in app.button if b.label=="生成公开报表决策").click().run()
    assert not app.exception
    run=deepcopy(app.session_state["runs"][0])
    for page in ("execution","delivery","company","solutions"):
        app.switch_page("app_pages/"+page+".py").run()
        assert not app.exception
    next(n for n in app.number_input if n.label=="历史资本开支倍数").set_value(1.5)
    next(b for b in app.button if b.label=="重新求解并保存下一版").click().run()
    assert not app.exception
    latest=app.session_state["runs"][0]
    assert latest["parent_run_id"]==run["id"]
    assert latest["raw_public"]==run["raw_public"]
    assert app.session_state["runs"][1]==run
    # In requested-financing mode changing financial assumptions must not rewrite the user's requested amount.
    assert latest["revision_delta"]["gap"]==0
    assert latest["public_analysis"]["gap"]>run["public_analysis"]["gap"]
    assert latest["revision_delta"]["debt_total"]<=0


def test_public_ai_exposes_professional_tools_and_finishes_with_independent_verification():
    import json
    from types import SimpleNamespace
    from finbridge.config import Settings
    from finbridge.task_agent import run_task_agent
    from finbridge.industry_context import SECTIONS
    engine=DiligenceRun(public_example(),{},"方案比较","模拟")
    ordered=("inspect_data","calculate_ratios","estimate_financing_need","assess_risk","retrieve_knowledge","simulate_repayment","match_routes","optimize_financing_portfolio","analyze_industry_region","verify_decision","prepare_deliverables")
    captured=[]
    def create(**kwargs):
        captured.append(kwargs)
        if kwargs.get("response_format"):
            result={"summary":"按公开数据情景比较期限。","funding_coverage_status":"unfunded","data_gaps":[]}
            result.update({k:[{"title":"公开数据边界","analysis":"现金与本息是公开报表代理情景，不能当合同计划。","metric_keys":[],"source_ids":[]}] for k in SECTIONS})
            message=SimpleNamespace(content=json.dumps(result))
        else:
            calls=[SimpleNamespace(id="call_"+str(i),function=SimpleNamespace(name=name,arguments="{}")) for i,name in enumerate(ordered)]
            message=SimpleNamespace(tool_calls=calls,model_dump=lambda **_:dict(role="assistant",tool_calls=[]))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    run=run_task_agent(engine,Settings("test-key","https://example.invalid","test"),client=client,source_search=lambda *_:[])
    assert run["mode"]=="AI 自主规划" and run["status"]=="已完成"
    names={tool["function"]["name"] for tool in captured[0]["tools"]}
    assert {"estimate_financing_need","verify_decision"}<=names
    assert run["outputs"]["verify_decision"]["passed"]
    assert len(run["events"])==11 and len(captured)==2


def test_market_research_never_weakens_user_selected_public_stress():
    from finbridge.market_rules import market_decision
    run=DiligenceRun(public_example(),{"cash_drop":.4,"rate_up":.03},"风险分析","模拟").local()
    decision=market_decision(run["data"],run["profile"],run["outputs"],[],[])
    assert decision["planning_stress"]["cash_drop"]==.4
    assert decision["planning_stress"]["rate_up"]==.03
    assert not decision["changed"]
