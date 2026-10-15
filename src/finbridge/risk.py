"""Transparent, illustrative financial risk checks; not a lending score."""

from __future__ import annotations

from typing import Mapping

from finbridge.analysis import calculate_deep_metrics


def analyze_financial_risk(data: Mapping[str, object]) -> dict[str, object]:
    """Return rule-based risk dimensions with evidence and data sufficiency."""
    ratios = calculate_deep_metrics(data)
    dimensions: dict[str, dict[str, object]] = {}

    def add_dimension(
        key: str,
        label: str,
        metric_names: tuple[str, ...],
        checks: tuple[tuple[str, str, float, str], ...],
    ) -> None:
        evidence = []
        levels = []
        for metric_name, operator, threshold, risk_level in checks:
            metric = ratios[metric_name]
            value = metric["value"]
            if value is None:
                continue
            triggered = value < threshold if operator == "<" else value > threshold
            evidence.append(
                {
                    "metric": metric["label"],
                    "value": value,
                    "unit": metric["unit"],
                    "period": metric["period"],
                    "rule": f"{metric_name} {operator} {threshold}",
                    "rule_label": metric["label"] + ("低于" if operator == "<" else "高于") + (f"{threshold:.0%}" if metric["unit"] == "%" else f"{threshold:g}{metric['unit']}"),
                    "triggered": triggered,
                }
            )
            if triggered:
                levels.append(risk_level)

        available = sum(ratios[name]["value"] is not None for name in metric_names)
        if available == 0:
            status = "数据不足"
            level = "无法判断"
        else:
            status = f"已评估 {available}/{len(metric_names)} 项"
            level = "较高" if "较高" in levels else "关注" if "关注" in levels else "暂未触发演示规则"
        dimensions[key] = {
            "label": label,
            "risk_level": level,
            "data_sufficiency": status,
            "evidence": evidence,
        }

    add_dimension(
        "liquidity",
        "短期偿债",
        ("current_ratio", "quick_ratio", "cash_ratio", "unrestricted_cash_ratio"),
        (("current_ratio", "<", 1.0, "较高"), ("current_ratio", "<", 1.5, "关注"),
         ("quick_ratio", "<", 0.8, "较高"), ("cash_ratio", "<", 0.2, "关注"),
         ("unrestricted_cash_ratio", "<", 0.2, "关注")),
    )
    add_dimension(
        "leverage",
        "长期偿债与杠杆",
        ("debt_to_asset_ratio", "interest_coverage"),
        (("debt_to_asset_ratio", ">", 0.7, "较高"), ("interest_coverage", "<", 1.0, "较高")),
    )
    add_dimension(
        "profitability",
        "盈利能力",
        ("net_profit_margin", "return_on_assets", "return_on_equity", "gross_profit_margin"),
        (("net_profit_margin", "<", 0.0, "较高"), ("gross_profit_margin", "<", 0.0, "较高")),
    )
    add_dimension(
        "cash_flow",
        "现金流质量",
        ("operating_cash_flow_to_net_profit", "operating_cash_flow_to_current_liabilities",
         "operating_cash_flow_margin"),
        (("operating_cash_flow_to_net_profit", "<", 0.8, "关注"),
         ("operating_cash_flow_margin", "<", 0.0, "较高")),
    )
    add_dimension(
        "debt_service",
        "融资偿付能力",
        ("dscr", "interest_burden", "financing_gap"),
        (("dscr", "<", 1.0, "较高"), ("dscr", "<", 1.2, "关注")),
    )

    return {
        "dimensions": dimensions,
        "methodology": "规则阈值仅用于演示筛查，不是银行授信评分或违约概率。",
        "thresholds_are_illustrative": True,
    }
