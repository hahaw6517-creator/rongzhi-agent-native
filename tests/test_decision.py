"""Decision budgets must close, respect blockers and preserve their evidence."""
from copy import deepcopy
import json

import pandas as pd
import pytest

from finbridge.decision import TARGET_DSCR, annual_annuity_factor, build_financing_plan
from finbridge.risk import analyze_financial_risk
from finbridge.workflow import check_data, clean_data, match_routes, simulate_repayment


@pytest.fixture
def inputs():
    data = clean_data(pd.read_csv("data/demo_diligence.csv").iloc[0].to_dict())
    profile = {"amount": 3_000_000.0, "internal_funds": 500_000.0, "months": 24,
               "assumed_rate": .055, "purpose": "经营周转", "receivables": "可提供", "collateral": "未确认", "industry": "高端制造"}
    return data, profile


def plan_for(data, profile, *, quality=None, risk=None, simulation=None):
    financial = dict(data, financing_need=profile.get("amount"), available_internal_funds=profile.get("internal_funds"))
    quality = quality if quality is not None else check_data(financial)
    risk = risk if risk is not None else analyze_financial_risk(financial)
    simulation = simulation if simulation is not None else simulate_repayment(financial, profile)
    routes = match_routes(financial, profile, quality, risk)
    return build_financing_plan(financial, profile, quality, risk, simulation, routes)


def test_budget_balances_and_does_not_treat_pending_money_as_funded(inputs):
    data, profile = inputs
    profile["amount"] = 8_000_000.0
    plan = plan_for(data, profile)
    funding = plan["funding"]
    assert funding["proposed_debt"] > 0
    assert funding["proposed_debt"] < funding["gap"]
    assert funding["internal_used"] + funding["proposed_debt"] + funding["non_debt_gap"] == pytest.approx(funding["need"])
    assert funding["allocated_total"] == pytest.approx(funding["need"] - funding["non_debt_gap"])
    assert funding["unallocated_gap"] == funding["non_debt_gap"]
    assert plan["decision"]["code"] == "resize"
    assert "尚未落实" in plan["decision"]["summary"]


def test_capacity_formula_and_requested_principal_pass_stress_target(inputs):
    data, profile = inputs
    profile["amount"] = 8_000_000.0
    plan = plan_for(data, profile)
    expected = max(0, data["cash_flow_available_for_debt_service"] * .8 / TARGET_DSCR - data["scheduled_debt_service"]) / annual_annuity_factor(.065, 24)
    assert plan["funding"]["debt_capacity"] <= expected
    assert expected - plan["funding"]["debt_capacity"] < .011
    assert plan["repayment"]["stress"]["dscr"] >= TARGET_DSCR
    assert plan["repayment"]["base"]["dscr"] > plan["repayment"]["stress"]["dscr"]
    assert plan["assumptions"]["cash_drop"] == .2
    assert plan["assumptions"]["rate_up"] == .01
    assert "非监管" in plan["assumptions"]["source"]


def test_demand_caps_capacity_and_main_and_backup_are_exclusive(inputs):
    data, profile = inputs
    profile["amount"] = 600_000.0
    plan = plan_for(data, profile)
    assert plan["funding"]["proposed_debt"] == 100_000.0
    assert plan["funding"]["non_debt_gap"] == 0
    assert plan["primary"]["amount"] == 100_000.0
    assert any(item["amount"] == 100_000.0 for item in plan["alternatives"] if item["route_id"] != "non_debt")
    assert "互斥" in plan["assumptions"]["allocation_rule"]
    assert plan["decision"]["code"] == "review"


@pytest.mark.parametrize("cash", [None, -100_000, 0, True, float("nan")])
def test_missing_invalid_or_nonpositive_cfads_never_produces_a_loan_amount(inputs, cash):
    data, profile = inputs
    data["cash_flow_available_for_debt_service"] = cash
    plan = plan_for(data, profile)
    assert plan["funding"]["proposed_debt"] is None
    assert plan["funding"]["debt_capacity"] is None
    assert plan["primary"]["amount"] is None
    assert not plan["repayment"]["available"]
    assert all(item["proposed_debt"] is None for item in plan["term_comparison"])
    json.dumps(plan, allow_nan=False)


def test_inconsistent_data_and_nonannual_inputs_pause_decision(inputs):
    data, profile = inputs
    data["current_assets"] = data["total_assets"] + 1
    plan = plan_for(data, profile)
    assert plan["decision"]["code"] == "correct_data"
    assert plan["funding"]["proposed_debt"] is None
    assert not plan["repayment"]["available"]
    data["current_assets"] = 4_800_000
    data["report_period"] = "2025年第一季度"
    plan = plan_for(data, profile)
    assert plan["decision"]["code"] == "supplement_data"
    assert plan["funding"]["proposed_debt"] is None


def test_high_risk_blocks_submission_despite_positive_mathematical_capacity(inputs):
    data, profile = inputs
    risk = analyze_financial_risk(data)
    risk["dimensions"]["profitability"]["risk_level"] = "较高"
    plan = plan_for(data, profile, risk=risk)
    assert plan["decision"]["code"] == "risk_review"
    assert plan["funding"]["debt_capacity"] > 0
    assert plan["funding"]["proposed_debt"] is None
    assert plan["primary"]["amount"] is None
    assert plan["repayment"]["available"]
    assert plan["repayment"]["budget_only"]
    assert all(row["proposed_debt"] is None for row in plan["term_comparison"])


def test_equipment_prioritizes_leasing_and_unconfirmed_collateral_remains_conditional(inputs):
    data, profile = inputs
    profile["purpose"] = "设备购置"
    plan = plan_for(data, profile)
    assert plan["primary"]["route_id"] == "leasing"
    secured = next(route for route in plan["route_ranking"] if route["route_id"] == "secured")
    assert secured["status"] == "条件方案"
    working = next(route for route in plan["route_ranking"] if route["route_id"] == "working")
    assert working["status"] == "用途不符"
    assert any("租金" in item for item in plan["limitations"])


def test_unconfirmed_receivables_do_not_become_a_main_financing_source(inputs):
    data, profile = inputs
    profile["receivables"] = "未确认"
    plan = plan_for(data, profile)
    assert plan["primary"]["route_id"] == "working"
    receivable = next(route for route in plan["alternatives"] if route["route_id"] == "receivable")
    assert receivable["amount"] is None
    assert receivable["status"] == "条件方案"


def test_zero_gap_does_not_allocate_excess_internal_funds(inputs):
    data, profile = inputs
    profile.update(amount=300_000, internal_funds=500_000)
    plan = plan_for(data, profile)
    assert plan["decision"]["code"] == "no_gap"
    assert not plan["decision"]["debt_allowed"]
    assert plan["funding"]["gap"] == 0
    assert plan["funding"]["proposed_debt"] == 0
    assert plan["funding"]["internal_used"] == 300_000
    assert plan["funding"]["allocated_total"] == 300_000
    assert all(item["amount"] is None for item in plan["alternatives"] if item["route_id"] != "non_debt")


def test_capacity_exhausted_by_existing_service_returns_zero_instead_of_negative_loan(inputs):
    data, profile = inputs
    data["cash_flow_available_for_debt_service"] = 750_000.0
    # CFADS covers existing debt, but the stricter stressed target leaves no new debt room.
    plan = plan_for(data, profile)
    assert plan["funding"]["debt_capacity"] == 0
    assert plan["funding"]["proposed_debt"] == 0
    assert plan["funding"]["non_debt_gap"] == plan["funding"]["gap"]
    assert plan["decision"]["code"] == "no_capacity"


@pytest.mark.parametrize("industry,expected", [
    ("高端制造", "manufacturing"), ("商贸批发", "commerce"), ("软件与信息服务", "software_technology"),
    ("酒店餐饮服务", "services"), ("食品制造", "agriculture_food"), ("工程施工", "construction"),
    ("生物技术研发", "generic"), ("未确认", "generic"),
])
def test_industry_branches_change_materials_without_inventing_industry_standards(inputs, industry, expected):
    data, profile = inputs
    profile["industry"] = industry
    plan = plan_for(data, profile)
    assert plan["industry"]["id"] == expected
    assert len(plan["industry"]["verification_materials"]) >= 4
    assert plan["industry"]["repayment_match"]
    assert plan["industry"]["pain_points"]


def test_term_comparison_is_unique_and_shows_cost_and_gap_tradeoffs(inputs):
    data, profile = inputs
    profile.update(amount=8_000_000.0, months=18)
    plan = plan_for(data, profile)
    terms = plan["term_comparison"]
    assert [term["months"] for term in terms] == [12, 18, 24, 36, 60]
    assert sum(term["selected"] for term in terms) == 1
    for term in terms:
        assert term["proposed_debt"] <= plan["funding"]["gap"]
        assert term["remaining_gap"] + term["proposed_debt"] == pytest.approx(plan["funding"]["gap"])
        assert term["stress_dscr"] >= TARGET_DSCR
    assert terms[-1]["debt_capacity"] > terms[0]["debt_capacity"]
    assert "周转周期待核验" in terms[-1]["status"]
    assert annual_annuity_factor(0, 24) == .5
    assert annual_annuity_factor(1e-14, 24) == pytest.approx(.5)


def test_snapshot_is_not_mutated_and_mismatched_simulation_pauses(inputs):
    data, profile = inputs
    before = deepcopy((data, profile))
    plan = plan_for(data, profile)
    assert (data, profile) == before
    json.dumps(plan, ensure_ascii=False, allow_nan=False)
    simulation = simulate_repayment(data, profile)
    simulation["gap"] += 100
    plan = plan_for(data, profile, simulation=simulation)
    assert plan["decision"]["code"] == "supplement_data"
    assert plan["funding"]["proposed_debt"] is None
