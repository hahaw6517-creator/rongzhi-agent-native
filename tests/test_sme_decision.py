from copy import deepcopy
import pytest
from finbridge.public_data import public_example
from finbridge.public_finance import public_model,NEEDED
from finbridge.public_portfolio import build_public_portfolio,verify_public_plan
from finbridge.sme_channels import match_sme_channels
from finbridge.sme_decision import review_and_adjust
from finbridge.workflow import DiligenceRun,report_markdown


def request(**changes):
    return dict(requested_amount=500_000.,requested_months=24,requested_purpose="经营周转",enterprise_type="中小微企业",**changes)


@pytest.mark.parametrize("goal",["融资组合","风险分析","方案比较"])
def test_sme_closed_loop(goal):
    raw=public_example();before=deepcopy(raw)
    run=DiligenceRun(raw,request(),goal,"虚构数据").local()
    assert len(run["events"])==12 and "review_financing_request" in run["outputs"]
    assert raw==before
    p=run["outputs"]["optimize_financing_portfolio"]
    assert p["sme_basis"] and p["funding"]["gap"]==500_000
    assert p["funding"]["internal_used"]==0 # external amount never double-deducts cash
    assert run["outputs"]["verify_decision"]["passed"]
    assert "中小微与科创" in report_markdown(run)
    assert run["outputs"]["prepare_deliverables"]["request_review"]


def test_only_necessary_public_values_and_no_invented_nwc():
    raw=public_example();minimal={k:v for k,v in raw.items() if k in NEEDED or k in {"company_name","industry","region","statement_schema","report_period"}}
    m=public_model(minimal,request())
    assert m["available"] and m["wc"] is None
    assert m["forecast_ocf"]==raw["operating_cash_flow"]
    assert any(r["kind"]=="数据缺口" for r in m["ledger"])
    run=DiligenceRun(minimal,request(),"风险分析","虚构最小集").local()
    assert run["status"]=="已完成"
    assert run["outputs"]["verify_decision"]["passed"]


def test_large_request_gets_quantified_independently_verified_alternative():
    profile={**request(),"requested_amount":5_000_000.}
    p=build_public_portfolio(public_example(),profile)
    review=review_and_adjust(p,public_example(),profile)
    assert review["reasonable"] is False
    alt=review["alternative"]
    assert alt["verified"] and 0<alt["amount"]<profile["requested_amount"]
    assert abs(alt["amount"]+alt["reduce_or_defer"]-profile["requested_amount"])<.01
    assert verify_public_plan(alt["portfolio"])["passed"]


def test_short_equipment_term_is_replanned_and_verified():
    profile={**request(),"requested_purpose":"设备购置","requested_months":12,"requested_amount":1_500_000.}
    p=build_public_portfolio(public_example(),profile)
    alt=review_and_adjust(p,public_example(),profile)["alternative"]
    assert alt["verified"] and alt["months"]>=36
    assert alt["amount"]>p["funding"]["debt_total"]
    assert any("固定资产" in c["name"] for c in alt["composition"])


def test_no_local_policy_or_tech_qualification_fabrication():
    raw={**public_example(),"region":"江苏苏州"}
    rows=match_sme_channels(raw,{**request(),"enterprise_type":"科创企业"})
    assert not next(c for c in rows if c["id"]=="sip_tech")["scope_match"]
    rows=match_sme_channels({**raw,"region":"江苏苏州工业园区"},{**request(),"enterprise_type":"科创企业"})
    assert next(c for c in rows if c["id"]=="sip_tech")["scope_match"]
    assert all(c["eligible"] is None and c["approved_limit"] is None and c["quoted_rate"] is None for c in rows)


def test_bullet_final_year_not_just_first_year_interest_and_tamper_detected():
    raw=public_example();p=build_public_portfolio(raw,request())
    bullet=next(c for c in p["composition"] if c["id"]=="receivable")
    # A platform product cannot borrow more merely by hiding the year-three principal.
    assert bullet["repayment"]=="bullet"
    p["composition"][1]["amount"]=5_000_000
    assert not verify_public_plan(p)["passed"]


def test_negative_cash_gets_no_fake_feasible_debt_solution():
    raw={**public_example(),"operating_cash_flow":-2_000_000.}
    p=build_public_portfolio(raw,request())
    review=review_and_adjust(p,raw,request())
    assert p["funding"]["debt_total"]==0
    assert not review["alternative"]["verified"]
    assert "存量" in review["alternative"]["explanation"]


def test_expired_product_register_blocks_allocation_without_blame_on_company(monkeypatch):
    import finbridge.sme_channels as channels
    monkeypatch.setattr(channels,"REGISTER",[{**c,"checked_on":"2000-01-01"} for c in channels.REGISTER])
    p=build_public_portfolio(public_example(),request())
    assert not p["available"]
    assert p["request_review"]["reasonable"] is None
    assert "更新产品来源" in p["request_review"]["status"]


def test_out_of_scope_and_absent_core_values_block_positive_result():
    for raw in ({**public_example(),"industry":"酒店旅游"},{**public_example(),"operating_cash_flow":None}):
        p=build_public_portfolio(raw,request())
        assert not p["available"] and not verify_public_plan(p)["passed"]


@pytest.mark.parametrize("profile",[{"requested_amount":float("nan")},{"requested_amount":100,"requested_months":2.5},{"requested_amount":100,"requested_purpose":"炒股"}])
def test_invalid_requests_rejected(profile):
    with pytest.raises(ValueError):public_model(public_example(),profile)


def test_software_research_purpose_works_and_uses_appropriate_focus():
    raw={**public_example(),"industry":"软件与信息技术服务","region":"江苏南京"}
    profile={**request(),"requested_purpose":"研发周转","enterprise_type":"科创企业"}
    run=DiligenceRun(raw,profile,"风险分析","虚构软件案例").local()
    plan=run["outputs"]["optimize_financing_portfolio"]
    assert run["status"]=="已完成" and plan["sector_model"]["key"]=="software"
    assert "receivables_days" in plan["sector_model"]["priority_metrics"]
    assert any("江苏" in c["name"] for c in plan["composition"])
    assert all(c["amount"]==0 for c in plan["composition"] if c["id"]=="leasing")


def test_ai_calls_demand_review_before_deliverables():
    import json
    from types import SimpleNamespace
    from finbridge.config import Settings
    from finbridge.task_agent import run_task_agent
    from finbridge.industry_context import SECTIONS
    engine=DiligenceRun(public_example(),request(),"融资组合","模拟")
    order=["inspect_data","calculate_ratios","estimate_financing_need","assess_risk","retrieve_knowledge","simulate_repayment","match_routes","optimize_financing_portfolio","analyze_industry_region","verify_decision","review_financing_request","prepare_deliverables"]
    def create(**kwargs):
        if kwargs.get("response_format"):
            payload=json.loads(kwargs["messages"][-1]["content"])
            response={"summary":"企业还款能力与用途匹配需共同核验。","funding_coverage_status":payload["funding_coverage_status"],"data_gaps":[]}
            response.update({key:[dict(title="财务依据",analysis="财报估算不能证明产品准入，按工具结果安排拟申请。",metric_keys=[],source_ids=[])] for key in SECTIONS})
            message=SimpleNamespace(content=json.dumps(response))
        else:
            assert "review_financing_request" in {t["function"]["name"] for t in kwargs["tools"]}
            calls=[SimpleNamespace(id=f"call_{i}",function=SimpleNamespace(name=tool,arguments="{}")) for i,tool in enumerate(order)]
            message=SimpleNamespace(tool_calls=calls,model_dump=lambda **_:dict(role="assistant",tool_calls=[]))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    run=run_task_agent(engine,Settings("fake","https://example.invalid","test"),client=client,source_search=lambda *_:[])
    assert run["mode"]=="AI 自主规划" and len(run["events"])==12
    assert run["outputs"]["analyze_industry_region"]["available"]
    assert run["outputs"]["prepare_deliverables"]["request_review"] is not None
