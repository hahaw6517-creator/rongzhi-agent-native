from copy import deepcopy
import pytest
from finbridge.adjustment import preview_adjustment
from finbridge.template import SIMULATED_EXAMPLE
from finbridge.workflow import DiligenceRun


def case(goal):
    return DiligenceRun(deepcopy(SIMULATED_EXAMPLE),dict(amount=3e6,internal_funds=5e5,months=24,assumed_rate=.055,
        purpose="经营周转",industry="精密制造",region="江苏苏州"),goal,"模拟").local()


@pytest.mark.parametrize("goal,changes",[
    ("融资组合",dict(internal_funds=6e5,confirmed_credit_limit=2e6)),
    ("风险分析",dict(cash_flow_available_for_debt_service=1e5,scheduled_debt_service=6e5)),
    ("方案比较",dict(cash_drop=.4,rate_up=.03)),
])
def test_adjustment_resolves_actual_constraints_without_mutating_original(goal,changes):
    run=case(goal)
    before=deepcopy(run)
    result=preview_adjustment(run,changes)
    assert run==before
    assert result["plan"]["available"] and result["focus"]["goal"]==goal
    assert result["plan"]["funding"] != run["outputs"]["optimize_financing_portfolio"]["funding"]
    assert all(c["used"] <= c["limit"]+.02 for c in result["plan"]["algorithm"]["constraints"])
    if goal=="风险分析":
        assert result["focus"]["risk"]["threshold"]["cash_improvement"] > 0
    if goal=="方案比较":
        assert result["plan"]["algorithm"]["planning_stress"]==changes
        assert result["focus"]["comparison"]["options"]


def test_adjustment_rejects_arbitrary_fields_and_keeps_market_pressure_basis():
    run=case("风险分析")
    with pytest.raises(ValueError):
        preview_adjustment(run,{"total_assets":1})
    with pytest.raises(ValueError):
        preview_adjustment(run,{"scheduled_debt_service":True})
    base=deepcopy(run["outputs"]["optimize_financing_portfolio"])
    base["algorithm"]["planning_stress"]={"cash_drop":.3,"rate_up":.02}
    run["outputs"]["analyze_industry_region"]["market_decision"]={"changed":True,"portfolio":base}
    result=preview_adjustment(run,{"cash_flow_available_for_debt_service":2e6})
    assert result["plan"]["algorithm"]["planning_stress"]==dict(cash_drop=.3,rate_up=.02)


def test_adjustment_form_runs_in_workspace_but_not_report():
    from streamlit.testing.v1 import AppTest
    run=case("风险分析")
    app=AppTest.from_file("../app.py",default_timeout=20).run()
    app.session_state["runs"]=[run]
    app.session_state["active_run_id"]=run["id"]
    app.session_state["task_checklists"]={run["id"]:run["outputs"]["prepare_deliverables"]["tasks"]}
    app.switch_page("app_pages/solutions.py").run()
    next(n for n in app.number_input if n.label=="试算年度还款现金（万元）").set_value(10.)
    next(b for b in app.button if b.label=="计算调整后的结果").click().run()
    assert not app.exception
    assert app.session_state["adjustment_result_"+run["id"]]["focus"]["risk"]["threshold"]["cash_improvement"]>0
    assert app.session_state["runs"][0]==run
    app.switch_page("app_pages/delivery.py").run()
    assert not any(b.label=="计算调整后的结果" for b in app.button)
