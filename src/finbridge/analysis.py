"""Financial operating drivers, with explicit source fields and no imputation."""
from __future__ import annotations

import math
from numbers import Real
import re
from typing import Mapping

from finbridge.finance import calculate_financial_ratios


SIGNED_FIELDS = frozenset({
    "net_profit", "prior_net_profit", "operating_profit", "ebit", "gross_profit",
    "income_tax_expense", "operating_cash_flow", "cash_flow_available_for_debt_service",
    "beginning_equity", "ending_equity",
})
ANNUAL_METRICS = frozenset({
    "return_on_assets", "return_on_equity", "receivables_turnover", "receivables_days",
    "inventory_turnover", "inventory_days", "total_asset_turnover",
    "operating_cash_flow_to_current_liabilities", "dscr", "debt_to_ebitda",
    "accounts_payable_days", "cash_conversion_cycle", "operating_cash_flow_to_debt",
})


def _annual_period(data: Mapping) -> bool:
    return bool(re.fullmatch(r"20\d{2}(?:年度|年|-12-31)?", str(data.get("report_period") or "").strip()))


def enriched_financial_data(data: Mapping) -> tuple[dict, list[dict]]:
    result, bridges = dict(data), []
    rules = (
        ("ebit", ("net_profit", "income_tax_expense", "interest_expense"), lambda x: sum(x), "净利润＋所得税费用＋利息费用；须核对损益口径"),
        ("gross_profit", ("revenue", "cost_of_goods_sold"), lambda x: x[0]-x[1], "营业收入－营业成本"),
        ("scheduled_debt_service", ("annual_principal_repayment", "annual_interest_payment"), lambda x: sum(x), "未来12个月到期本金＋未来12个月应付利息，覆盖全部存量有息债务"),
        ("cash_flow_available_for_debt_service", ("operating_cash_flow", "maintenance_capex"), lambda x: x[0]-x[1], "代理口径：经营活动现金流净额－维持性资本支出；需核验现金流分类、必要经营支出与一次性项目，不等同正式CFADS预测"),
    )
    for key, sources, compute, formula in rules:
        if result.get(key) is not None:
            continue
        try:
            values = _values(result, sources)
        except ValueError:
            continue
        derived = compute(values)
        if not math.isfinite(derived) or abs(derived) > 1e15:
            continue
        result[key] = derived
        bridges.append({"field": key, "sources": list(sources), "formula": formula, "value": result[key], "proxy": key == "cash_flow_available_for_debt_service"})
    return result, bridges


EXTRA_METRICS = {
    "working_capital": ("净营运资本", ("current_assets", "current_liabilities"), "元", "流动资产－流动负债", "短期资金缓冲，不等于可用现金。"),
    "unrestricted_cash": ("非受限货币资金", ("cash_and_equivalents", "restricted_cash"), "元", "货币资金－受限货币资金", "仍需扣除维持经营所需现金；不自动认定为可投入自有资金。"),
    "unrestricted_cash_ratio": ("非受限现金覆盖流动负债", ("cash_and_equivalents", "restricted_cash", "current_liabilities"), "倍", "(货币资金－受限货币资金) / 流动负债", "排除保证金、冻结款等受限货币资金；不代表全部流动负债立即到期，仍需核验必要经营留存与付款日期。"),
    "interest_bearing_debt": ("有息债务合计", ("short_term_debt", "long_term_debt", "current_portion_long_term_debt"), "元", "短期有息债务＋长期有息债务＋一年内到期长期债务", "长期债务填报应剔除已单列的一年内到期部分，避免重复。"),
    "net_debt": ("净有息债务", ("short_term_debt", "long_term_debt", "current_portion_long_term_debt", "cash_and_equivalents", "restricted_cash"), "元", "有息债务合计－非受限货币资金", "负值表示净现金，仍需核验可支配性。"),
    "ebitda": ("EBITDA", ("ebit", "depreciation_amortization"), "元", "息税前利润＋折旧摊销", "非会计准则统一列报项目，须保留桥接且不替代现金流。"),
    "debt_to_ebitda": ("有息债务 / EBITDA", ("short_term_debt", "long_term_debt", "current_portion_long_term_debt", "ebit", "depreciation_amortization"), "倍", "有息债务合计 / EBITDA", "EBITDA须为正；受行业资本密集程度影响，无统一安全线。"),
    "operating_profit_margin": ("营业利润率", ("operating_profit", "revenue"), "%", "营业利润 / 营业收入", "营业利润与息税前利润分别计算，不混用。"),
    "overdue_receivables_ratio": ("应收逾期占比", ("receivables_overdue", "ending_accounts_receivable"), "%", "逾期应收账款 / 期末应收账款", "应收账龄与逾期定义须按合同到期日核对。"),
    "receivables_over_90_ratio": ("逾期90天以上应收占比", ("receivables_over_90_days", "ending_accounts_receivable"), "%", "逾期90天以上应收 / 期末应收账款", "不据此直接认定坏账或推算获贷概率。"),
    "accounts_payable_days": ("应付账款周转天数", ("beginning_accounts_payable", "ending_accounts_payable", "cost_of_goods_sold"), "天", "平均应付账款 / 营业成本 × 365", "以营业成本近似赊购额，仅为周转分析口径。"),
    "cash_conversion_cycle": ("现金转换周期", ("beginning_accounts_receivable", "ending_accounts_receivable", "revenue", "beginning_inventory", "ending_inventory", "cost_of_goods_sold", "beginning_accounts_payable", "ending_accounts_payable"), "天", "应收周转天数＋存货周转天数－应付周转天数", "使用年度流量、平均余额及365天；不直接等同银行流贷需求测算。"),
    "cash_after_capex": ("经营现金流扣资本开支", ("operating_cash_flow", "capital_expenditure"), "元", "经营活动现金流净额－资本性支出", "观察投资后现金余量，与CFADS及未加杠杆自由现金流口径不同。"),
    "operating_cash_flow_to_debt": ("经营现金流 / 有息债务", ("operating_cash_flow", "short_term_debt", "long_term_debt", "current_portion_long_term_debt"), "%", "经营现金流净额 / 有息债务合计", "观察债务规模与年度现金流的相对关系。"),
}


def _values(data, fields):
    values = []
    for field in fields:
        value = data.get(field)
        if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("缺少有效数据：" + field)
        if value < 0 and field not in SIGNED_FIELDS:
            raise ValueError("金额不能为负：" + field)
        values.append(float(value))
    return values


def _divide(numerator, denominator):
    if denominator <= 0:
        raise ValueError("分母须大于0")
    return numerator / denominator


def calculate_deep_metrics(data: Mapping) -> dict:
    metrics = calculate_financial_ratios(data)
    metrics["cash_ratio"].update(
        label="货币资金总额 / 流动负债",
        interpretation="包含受限部分的货币资金总额覆盖口径，不能视为可自由支配现金的即时偿债能力。",
        applicability="与流动负债同一时点；判断可支配现金覆盖须另看非受限现金指标。",
    )
    for key, (label, fields, unit, formula, meaning) in EXTRA_METRICS.items():
        value, issue = None, None
        try:
            v = _values(data, fields)
            if key in {"working_capital", "unrestricted_cash", "cash_after_capex"}:
                value = v[0]-v[1]
                if key == "unrestricted_cash" and value < 0:
                    raise ValueError("受限货币资金不能大于货币资金")
            elif key == "unrestricted_cash_ratio":
                if v[1] > v[0]:
                    raise ValueError("受限货币资金不能大于货币资金")
                value = _divide(v[0]-v[1], v[2])
            elif key == "interest_bearing_debt":
                value = sum(v)
            elif key == "net_debt":
                if v[4] > v[3]:
                    raise ValueError("受限货币资金不能大于货币资金")
                value = sum(v[:3])-(v[3]-v[4])
            elif key == "ebitda":
                value = sum(v)
            elif key == "debt_to_ebitda":
                value = _divide(sum(v[:3]), sum(v[3:]))
            elif key in {"operating_profit_margin", "overdue_receivables_ratio", "receivables_over_90_ratio"}:
                value = _divide(v[0], v[1])
                if key != "operating_profit_margin" and not 0 <= value <= 1:
                    raise ValueError("逾期应收不能大于期末应收余额")
            elif key == "accounts_payable_days":
                value = _divide((v[0]+v[1])/2, v[2])*365
            elif key == "cash_conversion_cycle":
                value = _divide((v[0]+v[1])/2, v[2])*365+_divide((v[3]+v[4]-v[6]-v[7])/2, v[5])*365
            elif key == "operating_cash_flow_to_debt":
                value = _divide(v[0], sum(v[1:]))
        except ValueError as error:
            value, issue = None, str(error)
        metrics[key] = {"label": label, "value": value, "unit": unit, "formula": formula, "sources": list(fields), "period": str(data.get("report_period") or "未提供"), "interpretation": meaning, "applicability": meaning, "data_issue": issue}
    if not _annual_period(data):
        for key in ANNUAL_METRICS:
            metric = metrics[key]
            period_issue = "需确认完整年度报告期；中期或期间不明的数据不按全年计算，也不自动年化。"
            if metric["data_issue"]:
                period_issue += " " + metric["data_issue"]
            metric.update(value=None, data_issue=period_issue)
    return metrics


def financial_drivers(data: Mapping, metrics: Mapping) -> list[dict]:
    def val(name):
        return metrics.get(name, {}).get("value")
    drivers = []
    annual = _annual_period(data)
    if annual and val("receivables_days") is not None and val("receivables_days") > 0 and data.get("revenue", 0) > 0:
        days = min(15., val("receivables_days"))
        day_label = f"{days:.6g}"
        amount = data["revenue"] / 365 * days
        drivers.append({"title": f"回款提速{day_label}天的资金敏感性", "value": amount, "unit": "元", "improvement_days": days,
                        "reason": f"年度收入÷365×{day_label}天；改善天数不超过现有应收周转天数，表示同规模销售下的应收占用变化。实际须有真实回款安排，不等于已释放现金。", "action": "按客户和到期日分层催收，比较提前回款与融资手续费。"})
    if annual and val("inventory_days") is not None and val("inventory_days") > 0 and data.get("cost_of_goods_sold", 0) > 0:
        days = min(10., val("inventory_days"))
        day_label = f"{days:.6g}"
        drivers.append({"title": f"存货周转提速{day_label}天的占用敏感性", "value": data["cost_of_goods_sold"] / 365 * days, "unit": "元", "improvement_days": days,
                        "reason": f"年度营业成本÷365×{day_label}天；改善天数不超过现有存货周转天数，不包含采购折扣、停工或缺货影响，不能直接计入筹资总额。", "action": "核对呆滞和超期库存，结合订单安排分批采购。"})
    if annual and val("cash_conversion_cycle") is not None:
        drivers.append({"title": "经营资金占用周期", "value": val("cash_conversion_cycle"), "unit": "天", "reason": "应收天数＋存货天数－应付天数，定位资金沉淀环节；适用于有相关科目的企业。", "action": "使短期提款与采购、销售及回款节点匹配，避免单看净利润。"})
    if val("unrestricted_cash") is not None:
        reserve = data.get("minimum_cash_reserve")
        if isinstance(reserve, Real) and not isinstance(reserve, bool) and 0 <= reserve <= 1e15:
            drivers.append({"title": "扣除最低经营留存后的现金余量", "value": max(0, val("unrestricted_cash")-reserve), "unit": "元", "reason": "非受限货币资金－人工核验的最低经营现金留存；可用自有资金仍以确认输入为准。", "action": "保留工资、税费及供应商付款所需资金，再确定可投入金额。"})
    return drivers
