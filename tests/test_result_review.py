from copy import deepcopy

from finbridge.result_review import build_result_review, money
from finbridge.template import SIMULATED_EXAMPLE
from finbridge.workflow import DiligenceRun, report_html


def run_case(**changes):
    data = deepcopy(SIMULATED_EXAMPLE)
    data.update(changes)
    profile = dict(amount=3e6, internal_funds=5e5, months=24, assumed_rate=.055,
                   purpose="经营周转", industry="精密制造", region="江苏苏州")
    return DiligenceRun(data, profile, "融资组合", "测试虚构数据").local()


def test_zero_capacity_explains_actual_values_without_claiming_cashflow_is_insufficient():
    run = run_case(confirmed_credit_limit=0, eligible_receivables=0, unencumbered_collateral_value=0)
    review = build_result_review(run)
    assert run["outputs"]["optimize_financing_portfolio"]["funding"]["debt_total"] == 0
    assert any("四个渠道" in s for s in review["causes"])
    assert not any("占满" in s for s in review["causes"])
    assert review["channels"][0]["raw"] == 0
    assert "合格" in review["channels"][1]["field"]
    assert "本次实际采用的渠道输入" in report_html(run)


def test_zero_cashflow_budget_is_distinct_from_available_channel_capacity():
    run = run_case(cash_flow_available_for_debt_service=100000)
    review = build_result_review(run)
    assert review["service_budget"] == 0
    assert any("占满" in s for s in review["causes"])
    assert not any("四个渠道" in s for s in review["causes"])


def test_unknown_capacity_and_confirmed_zero_are_different():
    run = run_case(confirmed_credit_limit=None, eligible_receivables=0)
    rows = build_result_review(run)["channels"]
    assert rows[0]["status"] == "缺少容量依据"
    assert rows[1]["status"] == "输入明确为零"


def test_invalid_inputs_are_not_presented_as_zero_loan_results():
    run = run_case(current_assets=1e10)
    review = build_result_review(run)
    assert "暂不能" in review["title"]
    assert review["causes"]
    assert money("无法识别") == "无法识别（无效数值）"
