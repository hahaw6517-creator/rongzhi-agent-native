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
