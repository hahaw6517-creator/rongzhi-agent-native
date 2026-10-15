"""Pure Python financial metric calculations and input validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Callable, Mapping

MAX_AMOUNT = 1_000_000_000_000_000


def _number(value: object, field: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"缺少财务数据：{field}")
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field} 必须是数值")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{field} 必须是有限数值")
    return numeric_value


def _amount(value: object, field: str, *, allow_negative: bool = False) -> float:
    numeric_value = _number(value, field)
    lower_bound = -MAX_AMOUNT if allow_negative else 0
    if not lower_bound <= numeric_value <= MAX_AMOUNT:
        raise ValueError(f"{field} 必须在 {lower_bound} 到 {MAX_AMOUNT} 之间")
    return numeric_value


def calculate_debt_to_asset_ratio(total_liabilities: object, total_assets: object) -> float:
    """Return total liabilities divided by total assets as a decimal ratio."""
    liabilities = _amount(total_liabilities, "负债总额")
    assets = _amount(total_assets, "资产总额")
    if assets == 0:
        raise ValueError("资产总额必须大于 0")
    return liabilities / assets


def calculate_current_ratio(current_assets: object, current_liabilities: object) -> float:
    """Return current assets divided by current liabilities."""
    assets = _amount(current_assets, "流动资产")
    liabilities = _amount(current_liabilities, "流动负债")
    if liabilities == 0:
        raise ValueError("流动负债必须大于 0，无法计算流动比率")
    return assets / liabilities


def calculate_net_profit_margin(net_profit: object, revenue: object) -> float:
    """Return net profit divided by revenue as a decimal ratio."""
    profit = _amount(net_profit, "净利润", allow_negative=True)
    total_revenue = _amount(revenue, "营业收入")
    if total_revenue == 0:
        raise ValueError("营业收入必须大于 0，无法计算净利润率")
    return profit / total_revenue


METRIC_INPUTS: dict[str, tuple[str, ...]] = {
    "debt_to_asset_ratio": ("total_liabilities", "total_assets"),
    "current_ratio": ("current_assets", "current_liabilities"),
    "net_profit_margin": ("net_profit", "revenue"),
}

METRIC_LABELS = {
    "debt_to_asset_ratio": "资产负债率",
    "current_ratio": "流动比率",
    "net_profit_margin": "净利润率",
}



def _value(data: Mapping[str, object], field: str, *, allow_negative: bool = False) -> float:
    return _amount(data.get(field), field, allow_negative=allow_negative)


def _ratio(data: Mapping[str, object], numerator: str, denominator: str) -> float:
    top = _value(
        data,
        numerator,
        allow_negative=numerator in {
            "net_profit",
            "prior_net_profit",
            "operating_cash_flow",
            "cash_flow_available_for_debt_service",
            "ebit",
            "gross_profit",
        },
    )
    bottom = _value(data, denominator)
    if bottom == 0:
        raise ValueError(f"{denominator} 必须大于 0")
    return top / bottom


def _average_balance_ratio(data: Mapping[str, object], numerator: str, opening: str, closing: str) -> float:
    top = _value(data, numerator, allow_negative=numerator in {"net_profit"})
    average = (_value(data, opening) + _value(data, closing)) / 2
    if average == 0:
        raise ValueError(f"期初和期末平均余额必须大于 0：{opening}、{closing}")
    return top / average


def _days_ratio(data: Mapping[str, object], opening: str, closing: str, flow: str) -> float:
    average = (_value(data, opening) + _value(data, closing)) / 2
    flow_value = _value(data, flow)
    if flow_value == 0:
        raise ValueError(f"{flow} 必须大于 0")
    return average / flow_value * 365


def _growth(data: Mapping[str, object], current: str, prior: str) -> float:
    current_value = _value(data, current, allow_negative=current == "net_profit")
    prior_value = _value(data, prior, allow_negative=prior == "prior_net_profit")
    if prior_value <= 0:
        raise ValueError(f"{prior} 必须大于 0，才能计算可解释的同比增长率")
    return (current_value - prior_value) / prior_value


def _financing_gap(data: Mapping[str, object]) -> float:
    requested = _value(data, "financing_need")
    available = _value(data, "available_internal_funds")
    return max(0.0, requested - available)


@dataclass(frozen=True)
class MetricDefinition:
    formula: str
    fields: tuple[str, ...]
    unit: str
    interpretation: str
    applicability: str
    calculate: Callable[[Mapping[str, object]], float]


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "current_ratio": MetricDefinition(
        "流动资产 / 流动负债", ("current_assets", "current_liabilities"), "倍",
        "反映流动资产对流动负债的覆盖程度。", "流动负债须大于零。",
        lambda data: _ratio(data, "current_assets", "current_liabilities"),
    ),
    "quick_ratio": MetricDefinition(
        "速动资产 / 流动负债", ("quick_assets", "current_liabilities"), "倍",
        "反映扣除存货等变现较慢项目后的短期偿债能力。", "需提供明确的速动资产口径。",
        lambda data: _ratio(data, "quick_assets", "current_liabilities"),
    ),
    "cash_ratio": MetricDefinition(
        "货币资金 / 流动负债", ("cash_and_equivalents", "current_liabilities"), "倍",
        "衡量现金类资产对流动负债的即时覆盖。", "货币资金须与流动负债期间一致。",
        lambda data: _ratio(data, "cash_and_equivalents", "current_liabilities"),
    ),
    "debt_to_asset_ratio": MetricDefinition(
        "负债总额 / 资产总额", ("total_liabilities", "total_assets"), "%",
        "反映资产中由负债融资的比例，不代表授信结论。", "资产总额须大于零。",
        lambda data: _ratio(data, "total_liabilities", "total_assets"),
    ),
    "interest_coverage": MetricDefinition(
        "息税前利润（EBIT） / 利息费用", ("ebit", "interest_expense"), "倍",
        "衡量经营利润对利息费用的覆盖。", "需使用同一期间的 EBIT 和利息费用。",
        lambda data: _ratio(data, "ebit", "interest_expense"),
    ),
    "return_on_assets": MetricDefinition(
        "净利润 / ((期初总资产 + 期末总资产) / 2)",
        ("net_profit", "beginning_total_assets", "ending_total_assets"), "%",
        "衡量期间利润相对于平均资产的回报。", "必须提供同一期间期初、期末资产。",
        lambda data: _average_balance_ratio(data, "net_profit", "beginning_total_assets", "ending_total_assets"),
    ),
    "return_on_equity": MetricDefinition(
        "净利润 / ((期初所有者权益 + 期末所有者权益) / 2)",
        ("net_profit", "beginning_equity", "ending_equity"), "%",
        "衡量期间利润相对于平均所有者权益的回报。", "必须提供同一期间期初、期末权益。",
        lambda data: _average_balance_ratio(data, "net_profit", "beginning_equity", "ending_equity"),
    ),
    "net_profit_margin": MetricDefinition(
        "净利润 / 营业收入", ("net_profit", "revenue"), "%",
        "反映每单位营业收入形成的净利润。", "营业收入须大于零。",
        lambda data: _ratio(data, "net_profit", "revenue"),
    ),
    "gross_profit_margin": MetricDefinition(
        "毛利 / 营业收入", ("gross_profit", "revenue"), "%",
        "反映营业收入扣除营业成本后的毛利水平。", "需提供毛利和营业收入。",
        lambda data: _ratio(data, "gross_profit", "revenue"),
    ),
    "receivables_turnover": MetricDefinition(
        "营业收入 / ((期初应收账款 + 期末应收账款) / 2)",
        ("revenue", "beginning_accounts_receivable", "ending_accounts_receivable"), "次/年",
        "估算应收账款在期间内的周转次数。", "必须提供同口径期初、期末应收账款。",
        lambda data: _average_balance_ratio(data, "revenue", "beginning_accounts_receivable", "ending_accounts_receivable"),
    ),
    "receivables_days": MetricDefinition(
        "((期初应收账款 + 期末应收账款) / 2) / 营业收入 * 365",
        ("beginning_accounts_receivable", "ending_accounts_receivable", "revenue"), "天",
        "以营业收入近似赊销额估算应收账款周转天数。", "以总营业收入近似赊销额，结果需谨慎解释。",
        lambda data: _days_ratio(data, "beginning_accounts_receivable", "ending_accounts_receivable", "revenue"),
    ),
    "inventory_turnover": MetricDefinition(
        "营业成本 / ((期初存货 + 期末存货) / 2)",
        ("cost_of_goods_sold", "beginning_inventory", "ending_inventory"), "次/年",
        "衡量营业成本相对于平均存货的周转速度。", "必须提供同口径期初、期末存货。",
        lambda data: _average_balance_ratio(data, "cost_of_goods_sold", "beginning_inventory", "ending_inventory"),
    ),
    "inventory_days": MetricDefinition(
        "((期初存货 + 期末存货) / 2) / 营业成本 * 365",
        ("beginning_inventory", "ending_inventory", "cost_of_goods_sold"), "天",
        "估算存货周转所需天数。", "营业成本须大于零且期间一致。",
        lambda data: _days_ratio(data, "beginning_inventory", "ending_inventory", "cost_of_goods_sold"),
    ),
    "total_asset_turnover": MetricDefinition(
        "营业收入 / ((期初总资产 + 期末总资产) / 2)",
        ("revenue", "beginning_total_assets", "ending_total_assets"), "次/年",
        "衡量平均资产支持营业收入的效率。", "必须提供同一期间期初、期末资产。",
        lambda data: _average_balance_ratio(data, "revenue", "beginning_total_assets", "ending_total_assets"),
    ),
    "operating_cash_flow_to_net_profit": MetricDefinition(
        "经营活动现金流量净额 / 净利润", ("operating_cash_flow", "net_profit"), "倍",
        "比较经营现金流与会计利润的匹配程度。", "净利润须大于零；亏损期不计算该比值。",
        lambda data: _ratio(data, "operating_cash_flow", "net_profit"),
    ),
    "operating_cash_flow_to_current_liabilities": MetricDefinition(
        "经营活动现金流量净额 / 流动负债", ("operating_cash_flow", "current_liabilities"), "%",
        "衡量期间经营现金流对流动负债的覆盖。", "需确认现金流与负债数据期间口径。",
        lambda data: _ratio(data, "operating_cash_flow", "current_liabilities"),
    ),
    "operating_cash_flow_margin": MetricDefinition(
        "经营活动现金流量净额 / 营业收入", ("operating_cash_flow", "revenue"), "%",
        "衡量营业收入转化为经营现金流的比例。", "营业收入须大于零。",
        lambda data: _ratio(data, "operating_cash_flow", "revenue"),
    ),
    "revenue_growth": MetricDefinition(
        "(本期营业收入 - 上期营业收入) / 上期营业收入",
        ("revenue", "prior_revenue"), "%", "反映相邻可比期间营业收入变化。",
        "本期与上期长度、合并范围须可比；上期收入须大于零。",
        lambda data: _growth(data, "revenue", "prior_revenue"),
    ),
    "net_profit_growth": MetricDefinition(
        "(本期净利润 - 上期净利润) / 上期净利润",
        ("net_profit", "prior_net_profit"), "%", "反映相邻可比期间净利润变化。",
        "上期净利润须大于零；由亏转盈等情形不以该比率概括。",
        lambda data: _growth(data, "net_profit", "prior_net_profit"),
    ),
    "dscr": MetricDefinition(
        "可用于偿债现金流（CFADS） / 计划偿债本息",
        ("cash_flow_available_for_debt_service", "scheduled_debt_service"), "倍",
        "衡量可用于偿债现金流对计划本息支出的覆盖。", "不得以净利润替代 CFADS；必须提供明确偿债计划。",
        lambda data: _ratio(data, "cash_flow_available_for_debt_service", "scheduled_debt_service"),
    ),
    "interest_burden": MetricDefinition(
        "利息费用 / 营业收入", ("interest_expense", "revenue"), "%",
        "展示利息费用相对于营业收入的负担。", "营业收入须大于零；该比率不是利率。",
        lambda data: _ratio(data, "interest_expense", "revenue"),
    ),
    "financing_gap": MetricDefinition(
        "max(0, 融资需求 - 可用自有资金)", ("financing_need", "available_internal_funds"), "元",
        "估算外部融资需求，不代表可获批额度。", "需由用户明确提供融资需求及可用自有资金。",
        _financing_gap,
    ),
}


def calculate_financial_ratios(data: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Calculate supported ratios and retain formula, provenance fields, and limitations."""
    period = str(data.get("report_period") or data.get("period") or "未提供")
    results: dict[str, dict[str, object]] = {}
    for name, definition in METRIC_DEFINITIONS.items():
        try:
            input_issues = []
            for field in definition.fields:
                try:
                    _number(data.get(field), field)
                except ValueError as exc:
                    input_issues.append(str(exc))
            if input_issues:
                raise ValueError("；".join(input_issues))
            value = definition.calculate(data)
            error = None
        except (TypeError, ValueError) as exc:
            value = None
            error = str(exc)
        results[name] = {
            "label": METRIC_LABELS.get(name, name),
            "value": value,
            "formula": definition.formula,
            "sources": definition.fields,
            "unit": definition.unit,
            "period": period,
            "interpretation": definition.interpretation,
            "applicability": definition.applicability,
            "data_issue": error,
        }
    return results


def calculate_financial_metrics(data: Mapping[str, object]) -> dict[str, object]:
    """Calculate all available metrics and report missing/invalid inputs per metric."""
    detailed = calculate_financial_ratios(data)
    results: dict[str, object] = {"values": {}, "errors": {}}
    for metric in METRIC_INPUTS:
        result = detailed[metric]
        results["values"][metric] = result["value"]
        if result["data_issue"] is not None:
            results["errors"][metric] = result["data_issue"]
    return results