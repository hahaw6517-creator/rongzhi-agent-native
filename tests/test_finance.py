import pytest

from finbridge.finance import (
    METRIC_DEFINITIONS,
    calculate_current_ratio,
    calculate_debt_to_asset_ratio,
    calculate_financial_metrics,
    calculate_financial_ratios,
    calculate_net_profit_margin,
)


def test_debt_to_asset_ratio():
    assert calculate_debt_to_asset_ratio(40, 100) == pytest.approx(0.4)


def test_current_ratio():
    assert calculate_current_ratio(150, 100) == pytest.approx(1.5)


def test_net_profit_margin_supports_loss():
    assert calculate_net_profit_margin(-10, 100) == pytest.approx(-0.1)


@pytest.mark.parametrize(
    "calculation,arguments",
    [
        (calculate_debt_to_asset_ratio, (10, 0)),
        (calculate_current_ratio, (10, 0)),
        (calculate_net_profit_margin, (10, 0)),
        (calculate_current_ratio, (-1, 2)),
        (calculate_net_profit_margin, (True, 2)),
    ],
)
def test_financial_calculations_reject_invalid_values(calculation, arguments):
    with pytest.raises(ValueError):
        calculation(*arguments)


def test_metrics_report_missing_data_without_failing_all_metrics():
    result = calculate_financial_metrics(
        {"total_liabilities": 20, "total_assets": 100, "current_assets": None}
    )

    assert result["values"]["debt_to_asset_ratio"] == pytest.approx(0.2)
    assert result["values"]["current_ratio"] is None
    assert "缺少财务数据" in result["errors"]["current_ratio"]
    assert result["values"]["net_profit_margin"] is None


def test_professional_ratio_catalog_documents_formula_sources_and_period():
    ratios = calculate_financial_ratios({"report_period": "2025年度"})

    assert len(METRIC_DEFINITIONS) >= 20
    assert all(ratio["formula"] and ratio["sources"] and ratio["unit"] for ratio in ratios.values())
    assert all(ratio["period"] == "2025年度" for ratio in ratios.values())
    assert ratios["return_on_assets"]["value"] is None
    assert "beginning_total_assets" in ratios["return_on_assets"]["data_issue"]


def test_average_balance_metrics_use_both_period_ends():
    ratios = calculate_financial_ratios(
        {
            "net_profit": 30,
            "beginning_total_assets": 100,
            "ending_total_assets": 200,
            "revenue": 600,
        }
    )

    assert ratios["return_on_assets"]["value"] == pytest.approx(0.2)
    assert ratios["total_asset_turnover"]["value"] == pytest.approx(4.0)


def test_dscr_requires_cfads_and_scheduled_debt_service_not_net_profit():
    missing = calculate_financial_ratios(
        {"net_profit": 100, "scheduled_debt_service": 50}
    )["dscr"]
    calculated = calculate_financial_ratios(
        {
            "net_profit": 100,
            "cash_flow_available_for_debt_service": 60,
            "scheduled_debt_service": 50,
        }
    )["dscr"]

    assert missing["value"] is None
    assert calculated["value"] == pytest.approx(1.2)