from finbridge.risk import analyze_financial_risk


def test_risk_engine_reports_data_sufficiency_and_no_bank_score_claim():
    result = analyze_financial_risk({"report_period": "2025年度"})

    assert result["thresholds_are_illustrative"] is True
    assert "不是银行授信评分" in result["methodology"]
    assert result["dimensions"]["liquidity"]["risk_level"] == "无法判断"
    assert result["dimensions"]["liquidity"]["data_sufficiency"] == "数据不足"


def test_risk_rules_use_correct_direction_and_include_evidence():
    high_leverage = analyze_financial_risk(
        {"total_assets": 100, "total_liabilities": 80}
    )["dimensions"]["leverage"]
    low_leverage = analyze_financial_risk(
        {"total_assets": 100, "total_liabilities": 40}
    )["dimensions"]["leverage"]

    assert high_leverage["risk_level"] == "较高"
    assert high_leverage["evidence"][0]["triggered"] is True
    assert low_leverage["risk_level"] == "暂未触发演示规则"


def test_restricted_cash_cannot_hide_low_spendable_cash_coverage():
    data = {"report_period": "2025年度", "current_assets": 300, "current_liabilities": 100,
            "cash_and_equivalents": 200, "restricted_cash": 190}
    liquidity = analyze_financial_risk(data)["dimensions"]["liquidity"]
    assert liquidity["risk_level"] == "关注"
    restriction_evidence = next(item for item in liquidity["evidence"] if item["rule"].startswith("unrestricted_cash_ratio"))
    assert restriction_evidence["triggered"]
    assert restriction_evidence["value"] == .1
    assert restriction_evidence["metric"] == "非受限现金覆盖流动负债"
    gross_evidence = next(item for item in liquidity["evidence"] if item["rule"].startswith("cash_ratio"))
    assert gross_evidence["value"] == 2
    assert "总额" in gross_evidence["metric"]
    assert not gross_evidence["triggered"]
    no_restrictions = analyze_financial_risk(dict(data, restricted_cash=0))["dimensions"]["liquidity"]
    assert no_restrictions["risk_level"] == "暂未触发演示规则"


def test_quarterly_cfads_does_not_trigger_or_clear_annual_debt_service_thresholds():
    data = {"report_period": "2025年第一季度", "cash_flow_available_for_debt_service": 50,
            "scheduled_debt_service": 100}
    debt_service = analyze_financial_risk(data)["dimensions"]["debt_service"]
    assert debt_service["risk_level"] == "无法判断"
    assert debt_service["data_sufficiency"] == "数据不足"
    assert debt_service["evidence"] == []
    annual = analyze_financial_risk(dict(data, report_period="2025年度"))["dimensions"]["debt_service"]
    assert annual["risk_level"] == "较高"
    assert any(item["triggered"] for item in annual["evidence"])
