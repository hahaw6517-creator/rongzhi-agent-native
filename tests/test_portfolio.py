"""Check that financing mixes come from constraints rather than fixed ratios."""
from copy import deepcopy
import json

import pytest

from finbridge.portfolio import build_financing_portfolio


@pytest.fixture
def inputs():
    data = {"company_name": "组合测试企业", "report_period": "2025年度", "industry": "精密制造",
            "total_assets": 10_000_000., "total_liabilities": 3_000_000., "current_assets": 5_000_000.,
            "current_liabilities": 2_000_000., "revenue": 12_000_000., "net_profit": 1_000_000.,
            "cash_flow_available_for_debt_service": 5_000_000., "scheduled_debt_service": 400_000.,
            "confirmed_credit_limit": 300_000., "eligible_receivables": 1_000_000.,
            "unencumbered_collateral_value": 2_000_000., "equipment_purchase_amount": 1_000_000.,
            "credit_rate": .03, "receivable_rate": .06, "secured_rate": .08, "leasing_rate": .09}
    profile = {"amount": 2_000_000., "internal_funds": 200_000., "assumed_rate": .055, "months": 24,
               "purpose": "经营周转", "industry": "高端制造"}
    quality = {"blocked": False, "invalid": [], "issues": [], "core_missing": [], "period_known": True}
    risk = {"dimensions": {"cash": {"label": "现金流", "risk_level": "暂未触发演示规则"}}}
    return data, profile, quality, risk


def by_id(result):
    return {item["id"]: item for item in result["composition"]}


def test_maximum_coverage_then_minimum_assumed_cost_changes_mix(inputs):
    result = build_financing_portfolio(*inputs)
    channels = by_id(result)
    assert result["available"]
    assert channels["credit"]["amount"] == 300_000
    assert channels["receivable"]["amount"] == 700_000
    assert channels["secured"]["amount"] == 800_000
    assert channels["leasing"]["amount"] == 0
    assert result["funding"]["debt_total"] == 1_800_000
    assert result["funding"]["unfunded_gap"] == 0
    inputs[0]["secured_rate"] = .01
    cheaper = by_id(build_financing_portfolio(*inputs))
    assert cheaper["secured"]["amount"] == 1_000_000
    assert cheaper["credit"]["amount"] == 300_000
    assert cheaper["receivable"]["amount"] == 500_000
    assert result["algorithm"]["checked_candidates"] > 1


def test_stress_budget_is_shared_and_never_multiplied_per_channel(inputs):
    inputs[0]["cash_flow_available_for_debt_service"] = 1_200_000.
    result = build_financing_portfolio(*inputs)
    annual_service = next(row for row in result["scenarios"] if row["id"] == "double")
    assert annual_service["new_annual_service"] <= result["algorithm"]["service_budget"] + .001
    assert annual_service["dscr"] >= 1.2 - 1e-9
    assert result["funding"]["unfunded_gap"] > 0
    assert sum(row["amount"] for row in result["composition"]) == pytest.approx(result["funding"]["debt_total"])


def test_coverage_has_priority_over_cheapest_channel_when_service_is_binding(inputs):
    data, _, _, _ = inputs
    data.update(cash_flow_available_for_debt_service=1_000_000., confirmed_credit_limit=3_000_000.,
                eligible_receivables=0., unencumbered_collateral_value=6_000_000.,
                credit_rate=.01, credit_months=6, secured_rate=.12, secured_months=60)
    result = build_financing_portfolio(*inputs)
    channels = by_id(result)
    # Cheap short credit consumes more next-twelve-month repayment capacity;
    # expensive long debt covers more principal under this declared first goal.
    assert channels["credit"]["amount"] == 0
    assert channels["secured"]["amount"] > 0
    assert result["algorithm"]["cost_coefficients"]["credit"] < result["algorithm"]["cost_coefficients"]["secured"]
    single_credit = next(row for row in result["alternatives"] if row["id"] == "single_credit")
    assert result["funding"]["debt_total"] > single_credit["debt_total"]


def test_equipment_purpose_excludes_credit_and_receivable(inputs):
    inputs[1]["purpose"] = "设备购置"
    result = build_financing_portfolio(*inputs)
    channels = by_id(result)
    assert channels["credit"]["amount"] == channels["receivable"]["amount"] == 0
    assert channels["leasing"]["amount"] <= 700_000
    assert channels["secured"]["amount"] <= 1_000_000
    assert result["purpose_allocation"]["working_debt"] == 0


def test_combined_use_respects_subbudgets_and_total_budget(inputs):
    data, profile, _, _ = inputs
    profile["purpose"] = "综合融资"
    data.update(working_capital_need=600_000., equipment_funding_need=1_400_000.)
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    channels = by_id(result)
    assert channels["credit"]["amount"] + channels["receivable"]["amount"] <= 600_000
    assert channels["leasing"]["amount"] <= 1_400_000
    assert result["funding"]["debt_total"] <= 1_800_000
    allocation = result["purpose_allocation"]
    assert allocation["working_debt"] + allocation["working_internal"] + allocation["working_unfunded"] == pytest.approx(600_000)
    assert allocation["equipment_debt"] + allocation["equipment_internal"] + allocation["equipment_unfunded"] == pytest.approx(1_400_000)
    assert allocation["working_unfunded"] + allocation["equipment_unfunded"] == pytest.approx(result["funding"]["unfunded_gap"])
    data["equipment_funding_need"] = 2_000_000
    bad = build_financing_portfolio(*inputs)
    assert not bad["available"]
    assert bad["funding"]["debt_total"] is None


def test_current_working_purpose_key_precedes_legacy_total_requirement(inputs):
    data, profile, _, _ = inputs
    profile["purpose"] = "综合融资"
    data.update(working_capital_funding_need=600_000., working_capital_need=90_000_000., equipment_funding_need=1_400_000.)
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    assert result["purpose_allocation"]["working_capital_funding_need"] == 600_000
    assert not any("兼容读取旧字段" in item for item in result["risk_flags"])


@pytest.mark.parametrize("field,value", [("cash_flow_available_for_debt_service", None), ("cash_flow_available_for_debt_service", float("nan")),
                                         ("scheduled_debt_service", -1), ("report_period", "2025年第一季度"), ("total_assets", None)])
def test_missing_or_invalid_financial_inputs_do_not_create_positive_amounts(inputs, field, value):
    inputs[0][field] = value
    result = build_financing_portfolio(*inputs)
    assert not result["available"]
    assert result["funding"]["debt_total"] is None
    assert all(row["amount"] is None for row in result["composition"])
    assert result["scenarios"] == []
    json.dumps(result, allow_nan=False)


def test_quality_and_actual_amount_contradictions_block(inputs):
    inputs[2]["blocked"] = True
    assert not build_financing_portfolio(*inputs)["available"]
    inputs[2]["blocked"] = False
    inputs[0]["current_assets"] = inputs[0]["total_assets"] + 1
    assert not build_financing_portfolio(*inputs)["available"]


@pytest.mark.parametrize("cash", [0., -400_000.])
def test_nonpositive_cash_flow_has_zero_new_debt_instead_of_null_or_profit_substitution(inputs, cash):
    inputs[0]["cash_flow_available_for_debt_service"] = cash
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    assert result["funding"]["debt_total"] == 0
    assert result["funding"]["unfunded_gap"] == result["funding"]["gap"]
    assert all(row["amount"] == 0 for row in result["composition"])
    assert next(row for row in result["scenarios"] if row["id"] == "double")["cfads"] <= cash


def test_high_risk_preserves_conditional_budget_but_marks_it_prominently(inputs):
    inputs[3]["dimensions"]["cash"]["risk_level"] = "较高"
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    assert result["funding"]["debt_total"] > 0
    assert "较高风险" in result["risk_status"]
    assert any("较高风险" in item for item in result["risk_flags"])
    assert "较高风险" in result["recommendations"][0]["title"]
    assert not result["implementation_ready"]


def test_negative_cash_without_existing_debt_reports_operating_shortfall(inputs):
    inputs[0].update(cash_flow_available_for_debt_service=-100_000., scheduled_debt_service=0.)
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    assert result["funding"]["debt_total"] == 0
    severe = next(s for s in result["scenarios"] if s["id"] == "cash_drop_30")
    assert severe["dscr"] is None
    assert severe["gap_to_target"] == 130_000
    assert any("偿债本息为0" in s["quantification"] for s in result["recommendations"])


def test_book_values_are_not_eligible_financing_capacity(inputs):
    for key in ("confirmed_credit_limit", "eligible_receivables", "unencumbered_collateral_value", "equipment_purchase_amount"):
        inputs[0].pop(key)
    inputs[0].update(accounts_receivable=30_000_000., ending_accounts_receivable=30_000_000.)
    result = build_financing_portfolio(*inputs)
    assert result["available"]
    assert result["funding"]["debt_total"] == 0
    assert all(row["capacity"] == 0 for row in result["composition"])
    assert any("不从账面" in item for item in result["risk_flags"])


def test_zero_rate_and_custom_terms_support_comparison(inputs):
    data, profile, _, _ = inputs
    data.update(credit_rate=0., credit_months=12, credit_fee_rate=0., confirmed_credit_limit=3_000_000.)
    result = build_financing_portfolio(*inputs)
    credit = by_id(result)["credit"]
    assert credit["amount"] == 1_800_000
    assert credit["monthly_payment"] == 150_000
    assert credit["total_interest"] == 0
    assert credit["months"] == 12
    assert sum(row["share"] for row in result["composition"]) == pytest.approx(1.)


def test_short_contracts_count_actual_payments_once_in_next_twelve_months(inputs):
    data, _, _, _ = inputs
    data.update(credit_rate=0., credit_months=6, confirmed_credit_limit=3_000_000.,
                cash_flow_available_for_debt_service=3_500_000.)
    result = build_financing_portfolio(*inputs)
    credit = by_id(result)["credit"]
    assert credit["amount"] == 1_800_000
    base = next(row for row in result["scenarios"] if row["id"] == "base")
    assert base["new_annual_service"] == pytest.approx(credit["monthly_payment"] * 6)
    assert "不假定到期续贷" in result["repayment_note"]


def test_one_off_fees_are_separate_funding_gaps_and_affect_cost_order(inputs):
    inputs[0].update(credit_fee_rate=.5, secured_fee_rate=.01)
    result = build_financing_portfolio(*inputs)
    channels = by_id(result)
    assert channels["credit"]["amount"] == 100_000
    assert channels["receivable"]["amount"] == 700_000
    assert channels["secured"]["amount"] == 1_000_000
    funding = result["funding"]
    assert funding["fees_due"] == 60_000
    assert funding["fee_funding_gap"] == 60_000
    assert funding["total_cash_need"] == funding["need"] + 60_000
    assert funding["total_unfunded_cash"] == funding["unfunded_gap"] + 60_000


def test_zero_gap_never_borrows_or_overallocates_internal_funds(inputs):
    inputs[1].update(amount=100_000., internal_funds=500_000.)
    result = build_financing_portfolio(*inputs)
    assert result["funding"]["debt_total"] == 0
    assert result["funding"]["internal_used"] == 100_000
    assert result["funding"]["gap"] == 0
    assert result["status"] == "无需新增融资"


def test_currency_rounding_and_limits_do_not_break_constraints(inputs):
    inputs[1].update(amount=500_000.03, internal_funds=0.)
    inputs[0].update(confirmed_credit_limit=123_456.789, eligible_receivables=765_432.109)
    result = build_financing_portfolio(*inputs)
    for channel in result["composition"]:
        assert channel["amount"] <= channel["capacity"] + .0001
        assert channel["amount"] >= 0
    assert result["funding"]["debt_total"] <= result["funding"]["gap"] + .0001
    assert result["funding"]["debt_total"] + result["funding"]["unfunded_gap"] == pytest.approx(result["funding"]["gap"])


def test_only_current_four_candidates_are_claimed_optimal_and_inputs_stay_immutable(inputs):
    original = deepcopy(inputs)
    first = build_financing_portfolio(*inputs)
    second = build_financing_portfolio(*inputs)
    assert first == second
    assert inputs == original
    assert any("四个候选" in item and "不声称" in item for item in first["algorithm"]["assumptions"])
    assert any("剔除" in item or "排除" in item for item in first["algorithm"]["assumptions"])
    assert len(first["scenarios"]) == 5
    assert next(row for row in first["scenarios"] if row["id"] == "cash_drop_30")["cfads"] == 3_500_000
    json.dumps(first, allow_nan=False)
