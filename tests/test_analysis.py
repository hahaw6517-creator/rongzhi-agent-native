from finbridge.analysis import ANNUAL_METRICS, calculate_deep_metrics, enriched_financial_data, financial_drivers
import pytest


def test_bridges_require_full_sources_and_never_overwrite_verified_inputs():
    data, trace = enriched_financial_data({"net_profit": 100, "income_tax_expense": 30, "interest_expense": 20, "operating_cash_flow": 200, "maintenance_capex": 40, "annual_principal_repayment": 60, "annual_interest_payment": 10})
    assert data["ebit"] == 150
    assert data["cash_flow_available_for_debt_service"] == 160
    assert data["scheduled_debt_service"] == 70
    assert any(x["proxy"] for x in trace)
    verified, _ = enriched_financial_data(dict(data, cash_flow_available_for_debt_service=123))
    assert verified["cash_flow_available_for_debt_service"] == 123
    incomplete, _ = enriched_financial_data({"operating_cash_flow": 200})
    assert "cash_flow_available_for_debt_service" not in incomplete


def test_debt_cash_and_cycle_have_correct_sources_and_formulas():
    data = {"report_period": "2025年度", "cash_and_equivalents": 200, "restricted_cash": 50, "short_term_debt": 100, "long_term_debt": 200, "current_portion_long_term_debt": 20, "ebit": 120, "depreciation_amortization": 40, "beginning_accounts_receivable": 100, "ending_accounts_receivable": 200, "revenue": 1000, "beginning_inventory": 200, "ending_inventory": 100, "cost_of_goods_sold": 500, "beginning_accounts_payable": 60, "ending_accounts_payable": 40}
    metrics = calculate_deep_metrics(data)
    assert metrics["net_debt"]["value"] == 170
    assert metrics["debt_to_ebitda"]["value"] == 2
    assert metrics["cash_conversion_cycle"]["value"] == pytest.approx(150/1000*365 + 150/500*365 - 50/500*365)
    assert financial_drivers(data, metrics)[0]["value"] == pytest.approx(1000/365*15)


def test_missing_or_contradictory_inputs_do_not_invent_results():
    results = calculate_deep_metrics({"cash_and_equivalents": 100, "restricted_cash": 200})
    assert results["unrestricted_cash"]["value"] is None
    assert results["cash_conversion_cycle"]["value"] is None
    assert results["ebitda"]["value"] is None


@pytest.mark.parametrize("source,target,inputs", [
    ("maintenance_capex", "cash_flow_available_for_debt_service", {"operating_cash_flow": 100}),
    ("interest_expense", "ebit", {"net_profit": 100, "income_tax_expense": 20}),
    ("cost_of_goods_sold", "gross_profit", {"revenue": 100}),
    ("annual_principal_repayment", "scheduled_debt_service", {"annual_interest_payment": 10}),
    ("annual_interest_payment", "scheduled_debt_service", {"annual_principal_repayment": 100}),
])
def test_invalid_negative_source_never_creates_a_valid_derived_amount(source, target, inputs):
    data, trace = enriched_financial_data(dict(inputs, **{source: -900}))
    assert target not in data
    assert not any(item["field"] == target for item in trace)
    assert data[source] == -900  # Keep original input available for quality checks.


def test_tax_benefits_losses_and_negative_cfads_remain_valid_signed_inputs():
    data, trace = enriched_financial_data({
        "net_profit": 100, "income_tax_expense": -20, "interest_expense": 10,
        "revenue": 100, "cost_of_goods_sold": 120,
        "operating_cash_flow": -100, "maintenance_capex": 20,
    })
    assert data["ebit"] == 90
    assert data["gross_profit"] == -20
    assert data["cash_flow_available_for_debt_service"] == -120
    assert len(trace) == 3


@pytest.fixture
def annual_data():
    return {
        "report_period": "2025年度", "total_assets": 2000, "total_liabilities": 800,
        "current_assets": 1000, "current_liabilities": 400, "quick_assets": 700,
        "cash_and_equivalents": 200, "restricted_cash": 50,
        "beginning_total_assets": 1800, "ending_total_assets": 2000,
        "beginning_equity": 1100, "ending_equity": 1200,
        "revenue": 1000, "net_profit": 100, "gross_profit": 500,
        "cost_of_goods_sold": 500, "operating_profit": 150,
        "ebit": 200, "interest_expense": 20, "depreciation_amortization": 50,
        "beginning_accounts_receivable": 100, "ending_accounts_receivable": 200,
        "beginning_inventory": 100, "ending_inventory": 150,
        "beginning_accounts_payable": 50, "ending_accounts_payable": 70,
        "operating_cash_flow": 400, "capital_expenditure": 100,
        "cash_flow_available_for_debt_service": 300, "scheduled_debt_service": 100,
        "short_term_debt": 100, "long_term_debt": 200, "current_portion_long_term_debt": 20,
        "minimum_cash_reserve": 20,
    }


@pytest.mark.parametrize("period", ["2025年第一季度", "2025年半年度", "未注明", None])
def test_nonannual_data_pauses_annual_turnover_returns_and_stock_flow_ratios(annual_data, period):
    annual_metrics = calculate_deep_metrics(annual_data)
    assert all(annual_metrics[key]["value"] is not None for key in ANNUAL_METRICS)
    results = calculate_deep_metrics(dict(annual_data, report_period=period))
    for key in ANNUAL_METRICS:
        assert results[key]["value"] is None, key
        assert "完整年度报告期" in results[key]["data_issue"]
    # Ratios between comparable same-period flows and point-in-time balances
    # remain meaningful without pretending a quarterly amount is a full year.
    for key in ("current_ratio", "debt_to_asset_ratio", "net_profit_margin",
                "operating_cash_flow_to_net_profit", "operating_cash_flow_margin",
                "interest_coverage", "unrestricted_cash_ratio"):
        assert results[key]["value"] == annual_metrics[key]["value"]
    assert results["ebitda"]["value"] == 250
    assert results["cash_after_capex"]["value"] == 300


def test_nonannual_drivers_ignore_stale_annual_metrics_but_keep_cash_reserve_analysis(annual_data):
    stale_metrics = calculate_deep_metrics(annual_data)
    quarterly = dict(annual_data, report_period="2025年第一季度")
    drivers = financial_drivers(quarterly, stale_metrics)
    assert len(drivers) == 1
    assert drivers[0]["value"] == 130
    assert "现金余量" in drivers[0]["title"]
    assert not any("365" in item["reason"] for item in drivers)


def test_unrestricted_cash_coverage_does_not_assume_unknown_restrictions_are_zero():
    data = {"cash_and_equivalents": 200, "restricted_cash": 190, "current_liabilities": 100}
    results = calculate_deep_metrics(data)
    assert results["unrestricted_cash_ratio"]["value"] == pytest.approx(.1)
    assert results["cash_ratio"]["value"] == 2
    assert results["cash_ratio"]["label"] == "货币资金总额 / 流动负债"
    assert "受限" in results["cash_ratio"]["interpretation"]
    del data["restricted_cash"]
    assert calculate_deep_metrics(data)["unrestricted_cash_ratio"]["value"] is None
    assert calculate_deep_metrics(dict(data, restricted_cash=201))["unrestricted_cash_ratio"]["value"] is None
    assert calculate_deep_metrics(dict(data, restricted_cash=0, current_liabilities=0))["unrestricted_cash_ratio"]["value"] is None
