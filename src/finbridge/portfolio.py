"""Solve a bounded financing portfolio using transparent linear constraints.

Four candidate channels share one project gap and one stressed repayment budget.
The lexicographic objective maximizes principal covering that project gap, then
minimizes assumed lifetime interest plus one-off fees at that coverage. Fees
are paid separately and explicitly remain an additional funding requirement.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import math
from numbers import Real
import re
from typing import Any, Mapping, Sequence

from finbridge.decision import _industry, annual_annuity_factor

TARGET_DSCR = 1.20
STRESS_CASH_DROP = 0.20
STRESS_RATE_UP = 0.01
MAX_AMOUNT = 1e15
CHANNELS = (
    ("credit", "已确认信用额度", "confirmed_credit_limit", None, None),
    ("receivable", "应收账款融资", "eligible_receivables", "receivable_advance_rate", .7),
    ("secured", "抵质押融资", "unencumbered_collateral_value", "collateral_advance_rate", .5),
    ("leasing", "设备融资租赁", "equipment_purchase_amount", "leasing_advance_rate", .7),
)
CORE_FIELDS = ("total_assets", "total_liabilities", "current_assets", "current_liabilities", "revenue", "net_profit")


def _finite(value: Any, low: float = -MAX_AMOUNT, high: float = MAX_AMOUNT) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real) or not low <= value <= high:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _input(data: Mapping[str, Any], profile: Mapping[str, Any], key: str) -> Any:
    """A populated profile overrides uploaded data; empty optional fields do not."""
    value = profile.get(key)
    return data.get(key) if value is None or value == "" else value


def _money(value: float) -> str:
    return f"{value / 1e8:,.6f}亿元"


def _service_factor(rate: float, months: int) -> float:
    """Payment due in the next twelve months, including short contracts once."""
    return annual_annuity_factor(rate, months) * min(months, 12) / 12


def _solve_linear(rows: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float] | None:
    """Small Gaussian elimination with partial pivoting; singular vertices skip."""
    size = len(rhs)
    matrix = []
    for row, value in zip(rows, rhs):
        scale = max((abs(item) for item in row), default=0)
        if scale == 0:
            return None
        matrix.append([item / scale for item in row] + [value / scale])
    for column in range(size):
        pivot = max(range(column, size), key=lambda index: abs(matrix[index][column]))
        if abs(matrix[pivot][column]) < 1e-12:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [item / divisor for item in matrix[column]]
        for other in range(size):
            if other == column:
                continue
            factor = matrix[other][column]
            matrix[other] = [a - factor * b for a, b in zip(matrix[other], matrix[column])]
    result = [row[-1] for row in matrix]
    return result if all(math.isfinite(value) for value in result) else None


def _feasible(point: Sequence[float], constraints: Sequence[tuple[list[float], float]]) -> bool:
    return all(sum(a * x for a, x in zip(row, point)) <= bound + max(1e-7, abs(bound) * 2e-12)
               for row, bound in constraints)


def _optimize(capacities: list[float], stress_factors: list[float], costs: list[float], gap: float,
              service_budget: float, working_budget: float, equipment_budget: float) -> tuple[list[float], int, list[dict[str, Any]]]:
    """Enumerate every possible vertex of the four-variable bounded polytope."""
    size = len(capacities)
    constraints: list[tuple[list[float], float]] = []
    evidence = []
    for index, capacity in enumerate(capacities):
        upper, lower = [0.0] * size, [0.0] * size
        upper[index], lower[index] = 1.0, -1.0
        constraints.extend([(upper, capacity), (lower, 0.0)])
        evidence.append({"id": CHANNELS[index][0] + "_limit", "label": CHANNELS[index][1] + "上限", "coefficients": upper, "limit": capacity, "unit": "元"})
    extra = [
        ("gap", "全部新增本金不超过项目外部资金缺口", [1.0] * size, gap),
        ("debt_service", "双重压力下未来12个月新增偿债预算", stress_factors, service_budget),
        ("working_purpose", "信用与应收融资合计不超过经营用途子预算", [1.0, 1.0, 0.0, 0.0], working_budget),
        ("equipment_purpose", "设备租赁不超过设备用途子预算", [0.0, 0.0, 0.0, 1.0], equipment_budget),
    ]
    for key, label, row, bound in extra:
        constraints.append((row, bound))
        evidence.append({"id": key, "label": label, "coefficients": list(row), "limit": bound, "unit": "元/年" if key == "debt_service" else "元"})
    best = [0.0] * size
    best_coverage = best_cost = 0.0
    checked = 1
    for active in combinations(range(len(constraints)), size):
        point = _solve_linear([constraints[index][0] for index in active], [constraints[index][1] for index in active])
        if point is None:
            continue
        checked += 1
        if not _feasible(point, constraints):
            continue
        point = [max(0.0, value) for value in point]
        coverage, cost = sum(point), sum(amount * weight for amount, weight in zip(point, costs))
        coverage_tolerance = max(1e-6, abs(best_coverage) * 2e-12)
        cost_tolerance = max(1e-7, abs(best_cost) * 2e-12)
        better = coverage > best_coverage + coverage_tolerance
        tied = abs(coverage - best_coverage) <= coverage_tolerance
        if better or (tied and (cost < best_cost - cost_tolerance or (abs(cost - best_cost) <= cost_tolerance and tuple(point) > tuple(best)))):
            best, best_coverage, best_cost = point, coverage, cost
    # Conservative cent rounding preserves every upper-bound constraint.
    rounded = [math.floor(max(0.0, value) * 100 + 1e-6) / 100 for value in best]
    for index, capacity in enumerate(capacities):
        rounded[index] = min(rounded[index], math.floor(capacity * 100 + 1e-6) / 100)
    # Recover any cent lost by independent rounding when a feasible channel can
    # absorb it. This is only a four-cent currency adjustment, not a new ratio.
    for _ in range(size):
        choices = []
        for index in range(size):
            candidate = list(rounded)
            candidate[index] = round(candidate[index] + .01, 2)
            if sum(candidate) <= best_coverage + 1e-5 and _feasible(candidate, constraints):
                choices.append((costs[index], index, candidate))
        if not choices:
            break
        rounded = min(choices, key=lambda item: (item[0], item[1]))[2]
    return rounded, checked, evidence


def _costs(amount: float | None, channel: Mapping[str, Any]) -> dict[str, Any]:
    if amount is None:
        return {"monthly_payment": None, "total_interest": None, "total_fee": None}
    payment = amount * annual_annuity_factor(channel["rate"], channel["months"]) / 12
    return {"monthly_payment": payment, "total_interest": round(max(0, payment * channel["months"] - amount), 2),
            "total_fee": round(amount * channel["fee_rate"], 2)}


def build_financing_portfolio(data: Mapping[str, Any], profile: Mapping[str, Any], quality: Mapping[str, Any], risk: Mapping[str, Any], *, planning_stress: Mapping[str, Any] | None = None, selection_objective: str = "cost") -> dict[str, Any]:
    if data.get("statement_schema") == "public-v2":
        from finbridge.public_portfolio import build_public_portfolio
        return build_public_portfolio(data,profile,planning_stress,selection_objective)
    if selection_objective not in {"cost", "repayment"}:
        raise ValueError("不支持的组合选择目标")
    planning_stress = planning_stress or {}
    cash_drop = planning_stress.get("cash_drop", STRESS_CASH_DROP)
    rate_up = planning_stress.get("rate_up", STRESS_RATE_UP)
    if _finite(cash_drop, .2, .4) is None or _finite(rate_up, .01, .05) is None:
        raise ValueError("市场压力参数超出允许区间")
    """Return a purpose-constrained funding portfolio, not approved credit.

    All currency inputs are yuan. Channel ``*_rate`` and ``*_fee_rate`` inputs
    are decimal fractions; ``*_months`` are integer terms. Unknown eligibility
    amounts have zero capacity. Invalid or incomplete financial inputs instead
    produce null loan allocations, while nonpositive valid CFADS allows zero.
    """
    errors, flags = [], []
    need, internal = _finite(profile.get("amount"), 0), _finite(profile.get("internal_funds"), 0)
    rate, term = _finite(profile.get("assumed_rate"), 0, 1), _finite(profile.get("months"), 1, 120)
    if need is None or internal is None or rate is None or term is None or int(term) != term:
        errors.append("请确认非负需求与自有资金、有限假设利率及1至120个月的整数期限。")
    months = int(term) if term is not None and int(term) == term else 24
    fallback_rate = rate if rate is not None else .055
    purpose = profile.get("purpose")
    if purpose not in ("经营周转", "订单备货", "设备购置", "综合融资"):
        errors.append("资金用途未确认；须选择经营周转、订单备货、设备购置或综合融资。")
    need = round(need, 2) if need is not None else None
    internal = round(internal, 2) if internal is not None else None
    internal_used = min(need, internal) if need is not None and internal is not None else None
    gap = round(max(0.0, need - internal), 2) if need is not None and internal is not None else None
    cash_fields = {"cash_and_equivalents": "货币资金", "restricted_cash": "受限货币资金", "minimum_cash_reserve": "最低经营现金储备"}
    cash_sources = {}
    for key, label in cash_fields.items():
        raw = _input(data, profile, key)
        cash_sources[key] = _finite(raw, 0)
        if raw not in (None, "") and cash_sources[key] is None:
            errors.append(f"自有资金来源字段{label}须为有限非负金额。")
    raw_additional = _input(data, profile, "confirmed_additional_internal_funds")
    additional_internal = 0.0 if raw_additional in (None, "") else _finite(raw_additional, 0)
    if additional_internal is None:
        errors.append("已落实额外自有资金须为有限非负金额，且不得包含新增借款或重复计入账面现金。")
    cash_group_complete = all(value is not None for value in cash_sources.values())
    cash_surplus = internal_source_limit = internal_source_excess = None
    if cash_group_complete:
        cash, restricted, reserve = (cash_sources[key] for key in cash_fields)
        if restricted > cash:
            errors.append("自有资金来源矛盾：受限货币资金大于货币资金。")
            cash_group_complete = False
        else:
            cash_surplus = round(max(0.0, cash - restricted - reserve), 2)
            if additional_internal is not None:
                internal_source_limit = round(cash_surplus + additional_internal, 2)
                internal_source_excess = round(max(0.0, internal - internal_source_limit), 2) if internal is not None else None
                if internal_source_excess is not None and internal_source_excess > .01:
                    errors.append(f"本次可用自有资金{_money(internal)}超过可核验来源上限{_money(internal_source_limit)}，差额{_money(internal_source_excess)}；请补充已落实非借款资金或修正投入金额。")
            if reserve > cash - restricted:
                flags.append("按填报现金基准，非受限货币资金尚不足最低经营留存；其差额不计入本项目可投入自有资金，需另核现金计划。")
    if internal_source_limit is not None:
        internal_source_note = (f"按填报现金基准，货币资金扣受限及最低留存后的余量{_money(cash_surplus)}，"
                                f"加已落实额外非借款自有资金{_money(additional_internal)}，来源上限{_money(internal_source_limit)}。"
                                "额外资金须排除账面已有现金；报表后资金变化须与本次资金计划基准核对，不能自动视为已落实资金。")
    else:
        internal_source_note = ("货币资金、受限部分、最低经营留存或额外自有资金尚未完整有效确认，自有资金来源暂无法闭环；"
                                "缺失现金项目不补0，未提供的额外资金按无已确认来源计入0。历史余额与本次计划仍须对齐时间基准。")
        flags.append(internal_source_note)
    if purpose == "综合融资":
        equipment_budget = _finite(_input(data, profile, "equipment_funding_need"), 0)
        working_input = _input(data, profile, "working_capital_funding_need")
        if working_input in (None, ""):
            working_input = _input(data, profile, "working_capital_need")
            if working_input not in (None, ""):
                flags.append("本次周转用途子预算兼容读取旧字段working_capital_need；须确认为本次用途需求，不能混用银行核定的营运资金总需求测算口径。")
        working_budget = _finite(working_input, 0)
        if equipment_budget is None or working_budget is None or need is None or not math.isclose(equipment_budget + working_budget, need, abs_tol=.011, rel_tol=1e-12):
            errors.append("综合融资须填写设备与经营用途子预算，合计须等于资金需求总额；不能把子预算另加到融资缺口。")
        equipment_budget, working_budget = equipment_budget or 0.0, working_budget or 0.0
    elif purpose == "设备购置":
        equipment_budget, working_budget = need or 0.0, 0.0
    else:
        equipment_budget, working_budget = 0.0, need or 0.0

    annual = bool(re.fullmatch(r"20\d{2}(?:年度|年|-12-31)?", str(data.get("report_period") or "").strip()))
    cfads, existing = _finite(data.get("cash_flow_available_for_debt_service")), _finite(data.get("scheduled_debt_service"), 0)
    if not annual or cfads is None or existing is None:
        errors.append("需同一年度的CFADS和非负现有年度偿债本息；缺失或中期数据不自动年化，也不用净利润替代。")
    debt_payments = {}
    for key, label in (("annual_principal_repayment", "未来12个月应还本金"), ("annual_interest_payment", "未来12个月应付利息")):
        raw = data.get(key)
        value = _finite(raw, 0)
        if raw not in (None, "") and value is None:
            errors.append(f"{label}须为有限非负金额。")
        if value is not None:
            debt_payments[key] = value
    if debt_payments and existing is not None and sum(debt_payments.values()) > existing + .011:
        errors.append("现有年度偿债本息小于已知本金与利息分项之和；不能因另一分项缺失而省略已知存量还款。")
    debt_balances = {}
    for key, label in (("short_term_debt", "短期有息债务"), ("long_term_debt", "长期有息债务"), ("current_portion_long_term_debt", "一年内到期长期债务")):
        raw = data.get(key)
        value = _finite(raw, 0)
        if raw not in (None, "") and value is None:
            errors.append(f"{label}须为有限非负金额，缺失与已确认0须区分。")
        if value is not None:
            debt_balances[key] = value
    for keys, upper_key, label in ((tuple(debt_balances), "total_liabilities", "全部负债"),
                                   (("short_term_debt", "current_portion_long_term_debt"), "current_liabilities", "流动负债")):
        known = [debt_balances[key] for key in keys if key in debt_balances]
        upper = _finite(data.get(upper_key), 0)
        if known and upper is not None and sum(known) > upper + .011:
            errors.append(f"已知有息债务分项小计超过{label}，请核对重复计入或金额；未提供的债务项目不擅自补0。")
    historical_maturing = sum(debt_balances[key] for key in ("short_term_debt", "current_portion_long_term_debt") if key in debt_balances)
    known_principal = debt_payments.get("annual_principal_repayment")
    if historical_maturing > 0 and (known_principal is None or historical_maturing > known_principal + .011):
        flags.append(f"填报余额中短期及一年内到期债务小计{_money(historical_maturing)}，与未来12个月本金计划须核对同一时间基准；历史余额不自动替代未来还款，也不能默认续贷后无需偿还。")
    if quality.get("blocked") or quality.get("invalid") or quality.get("issues"):
        errors.append("数据核验存在无效字段或金额关系矛盾，先修正后求解组合。")
    missing_core = [field for field in CORE_FIELDS if _finite(data.get(field), -MAX_AMOUNT if field == "net_profit" else 0) is None]
    if missing_core or quality.get("core_missing") or not quality.get("period_known"):
        errors.append("核心财务字段或报告期未确认，不能形成肯定融资金额。")
    for lower, upper in (("current_assets", "total_assets"), ("current_liabilities", "total_liabilities"), ("quick_assets", "current_assets"), ("cash_and_equivalents", "current_assets")):
        a, b = _finite(data.get(lower)), _finite(data.get(upper))
        if a is not None and b is not None and a > b:
            errors.append(f"金额关系矛盾：{lower}大于{upper}。")
    channels = []
    for channel_id, name, capacity_key, advance_key, default_advance in CHANNELS:
        raw_capacity = _input(data, profile, capacity_key)
        eligibility = _finite(raw_capacity, 0)
        if raw_capacity is not None and raw_capacity != "" and eligibility is None:
            errors.append(f"{name}的已确认基础金额无效。")
        if eligibility is None:
            flags.append(f"{name}：未提供{capacity_key}，本渠道容量按0处理；不从账面资产、应收或税务数据推断。")
            eligibility = 0.0
        raw_advance = _input(data, profile, advance_key) if advance_key else 1.0
        advance = _finite(raw_advance, 0, 1) if raw_advance not in (None, "") else default_advance
        if advance is None:
            errors.append(f"{name}规划折扣须在0至1之间。")
            advance = 0.0
        raw_rate = _input(data, profile, channel_id + "_rate")
        channel_rate = fallback_rate if raw_rate in (None, "") else _finite(raw_rate, 0, 1)
        raw_fee = _input(data, profile, channel_id + "_fee_rate")
        fee = 0.0 if raw_fee in (None, "") else _finite(raw_fee, 0, 1)
        raw_months = _input(data, profile, channel_id + "_months")
        channel_months = months if raw_months in (None, "") else _finite(raw_months, 1, 120)
        if channel_rate is None or fee is None or channel_months is None or int(channel_months) != channel_months:
            errors.append(f"{name}利率、费用或整数期限参数无效。")
            channel_rate, fee, channel_months = fallback_rate, 0.0, months
        enabled = purpose != "设备购置" if channel_id in {"credit", "receivable"} else purpose in {"设备购置", "综合融资"} if channel_id == "leasing" else True
        capacity = math.floor(eligibility * advance * 100 + 1e-6) / 100 if enabled else 0.0
        reason = f"基础{_money(eligibility)}×规划折扣{advance:.0%}，上限{_money(capacity)}。" if advance_key else f"仅使用已获批未使用独立信用额度{_money(eligibility)}，不推断自动授信。"
        if not enabled:
            reason = "本次用途不匹配，本渠道配置为0。"
        assumed = ["利率、费用及期限用于用户情景规划，真实报价和机构条件尚未核验。"]
        if advance_key:
            assumed.append(f"{advance:.0%}折扣为{'人工输入' if raw_advance not in (None, '') else '项目默认'}规划假设，不是行业标准或机构承诺。")
        if raw_fee in (None, ""):
            assumed.append("一次性费率0仅为未知费用的占位假设，不代表实际免收费。")
        channels.append({"id": channel_id, "name": name, "capacity": capacity, "eligibility_basis": eligibility,
                         "capacity_input": capacity_key, "advance_rate": advance, "rate": channel_rate,
                         "months": int(channel_months), "fee_rate": fee, "reason": reason, "assumed": assumed,
                         "enabled": enabled})
    if equipment_budget > 0 and channels[3]["eligibility_basis"] > equipment_budget + .011:
        flags.append("设备采购基础金额超过设备用途子预算，租赁配置仍受用途子预算限制；请核对采购范围与金额口径。")
    high_risks, concerns = [], []
    for key, dimension in risk.get("dimensions", {}).items():
        if not isinstance(dimension, Mapping):
            continue
        if dimension.get("risk_level") == "较高":
            high_risks.append(str(dimension.get("label", key)))
        elif dimension.get("risk_level") == "关注":
            concerns.append(str(dimension.get("label", key)))
    if high_risks:
        flags.insert(0, "较高风险：" + "、".join(high_risks) + "；本组合仅为条件预算，先人工复核与整改，不表示可获批。")
    if concerns:
        flags.append("需关注并复核：" + "、".join(concerns) + "。")
    flags.append("关键前提：四个融资池为独立可叠加的未占用容量，不能互相占用同一授信；抵质押基础必须剔除用于应收融资的同一债权、租赁设备及其他已占用资产。未验证池独立前不能实施组合。")
    errors = list(dict.fromkeys(errors))
    available = not errors
    stress_cfads = cfads * (1 - cash_drop) if cfads is not None and cfads >= 0 else cfads * (1 + cash_drop) if cfads is not None else None
    service_budget = max(0.0, stress_cfads / TARGET_DSCR - existing) if available else None
    capacities = [channel["capacity"] for channel in channels]
    stress_factors = [_service_factor(channel["rate"] + rate_up, channel["months"]) for channel in channels]
    cost_weights = [max(0.0, annual_annuity_factor(channel["rate"], channel["months"]) * channel["months"] / 12 - 1) + channel["fee_rate"] for channel in channels]
    amounts, checked, constraint_evidence = ([None] * 4, 0, [])
    if available:
        amounts, checked, constraint_evidence = _optimize(capacities, stress_factors, stress_factors if selection_objective == "repayment" else cost_weights, gap, service_budget, working_budget, equipment_budget)
        for constraint in constraint_evidence:
            used = sum(amount * coefficient for amount, coefficient in zip(amounts, constraint["coefficients"]))
            constraint.update(used=used, remaining=max(0.0, constraint["limit"]-used), binding=abs(constraint["limit"]-used) <= 1)
    debt_total = round(sum(amounts), 2) if available else None
    composition = []
    for index, (amount, channel) in enumerate(zip(amounts, channels)):
        item = deepcopy(channel)
        item.update(amount=amount, share=amount / debt_total if debt_total else 0.0 if available else None,
                    **_costs(amount, channel))
        if amount and available:
            item["reason"] += " 在渠道容量、用途与压力偿付约束内，由最大覆盖优先的求解结果配置；覆盖相同时，按本方案设定的成本或未来一年还款负担目标选择。"
        if available and channel["enabled"] and channel["capacity"] > 0:
            item["reason"] += f" 每0.01亿元本金占用双重压力下未来12个月本息预算{_money(1_000_000 * stress_factors[index])}，全期限假设利息及费用{_money(1_000_000 * cost_weights[index])}。"
        composition.append(item)
    fees = round(sum(item["total_fee"] for item in composition), 2) if available else None
    interest = round(sum(item["total_interest"] for item in composition), 2) if available else None
    unfunded = round(max(0.0, gap - debt_total), 2) if available else gap
    fee_funding_gap = max(0.0, round(fees - max(0.0, internal - internal_used), 2)) if available else None
    scenarios = []
    if available:
        for scenario_id, label, drop, up in (("base", "基准情景", 0, 0), ("cash_drop", f"CFADS下降{cash_drop:.0%}", cash_drop, 0),
                                              ("rate_up", f"利率上行{rate_up*100:g}个百分点", 0, rate_up), ("double", "双重压力", cash_drop, rate_up),
                                              ("cash_drop_30", "额外探索：CFADS下降30%", .3, 0)):
            cash = cfads * (1 - drop) if cfads >= 0 else cfads * (1 + drop)
            service = sum(amount * _service_factor(channel["rate"] + up, channel["months"]) for amount, channel in zip(amounts, channels))
            total_service = service + existing
            scenarios.append({"id": scenario_id, "label": label, "cfads": cash, "cash_drop": drop, "rate_up": up,
                              "new_annual_service": service, "existing_annual_service": existing,
                              "dscr": cash / total_service if total_service > 0 else None,
                              "gap_to_target": max(0.0, TARGET_DSCR * total_service - cash),
                              "target_met": cash + 1e-7 >= TARGET_DSCR * total_service,
                              "note": "gap_to_target为达到项目DSCR目标尚缺的年度CFADS金额，不是新的贷款额度或营收预测。"})
    purpose_allocation = {"working_capital_need": working_budget, "working_capital_funding_need": working_budget, "equipment_funding_need": equipment_budget,
                          "working_debt": None, "equipment_debt": None, "working_internal": None, "equipment_internal": None,
                          "working_unfunded": None, "equipment_unfunded": None,
                          "note": "信用与应收限经营用途，租赁限设备用途；抵质押与自有资金按剩余用途缺口分配，合计不超单一总预算。"}
    if available:
        working_debt = amounts[0] + amounts[1]
        equipment_debt = amounts[3]
        secured_working = min(amounts[2], max(0, working_budget - working_debt))
        working_debt += secured_working
        equipment_debt += amounts[2] - secured_working
        working_internal = min(internal_used, max(0, working_budget - working_debt))
        equipment_internal = internal_used - working_internal
        purpose_allocation.update(working_debt=round(working_debt, 2), equipment_debt=round(equipment_debt, 2),
                                  working_internal=round(working_internal, 2), equipment_internal=round(equipment_internal, 2),
                                  working_unfunded=round(max(0, working_budget - working_debt - working_internal), 2),
                                  equipment_unfunded=round(max(0, equipment_budget - equipment_debt - equipment_internal), 2))
    alternatives = []
    if available:
        for index, channel in enumerate(channels):
            cap = min(channel["capacity"], gap, service_budget / stress_factors[index])
            if channel["id"] in {"credit", "receivable"}:
                cap = min(cap, working_budget)
            if channel["id"] == "leasing":
                cap = min(cap, equipment_budget)
            amount = math.floor(max(0.0, cap) * 100 + 1e-6) / 100
            if amount <= 0:
                continue
            costs = _costs(amount, channel)
            denominator = existing + amount * stress_factors[index]
            alternatives.append({"id": "single_" + channel["id"], "title": "仅使用" + channel["name"],
                                 "debt_total": amount, "unfunded_gap": round(gap - amount, 2),
                                 "stress_dscr": stress_cfads / denominator if denominator else None,
                                 "monthly_payment": costs["monthly_payment"], "total_cost": costs["total_interest"] + costs["total_fee"],
                                 "fees_due": costs["total_fee"],
                                 "reason": "同一需求与压力偿付预算下的单渠道对照；替代当前组合，不与当前组合金额相加。"})
    recommendations = []
    if errors:
        recommendations.append({"title": "先补齐输入，暂不配置肯定融资金额", "reason": "；".join(errors),
                                "quantification": "当前已知项目缺口为" + (_money(gap) if gap is not None else "待确认"), "action": "按报告期核对CFADS、现有偿债、用途和已确认的渠道基础金额后重新求解。"})
    else:
        positive = [item["name"] for item in composition if item["amount"] > 0]
        recommendations.append({"title": "按约束求解的融资组合" if positive else "当前不配置新增债务", "reason": " + ".join(positive) if positive else "现有容量、用途或压力偿付预算不能支持新增配置。",
                                "quantification": f"项目缺口{_money(gap)}；本金预算{_money(debt_total)}；用途缺口{_money(unfunded)}。",
                                "action": "逐项核验容量依据、实际报价及合同现金流；未核验前仅作准备预算。"})
        if unfunded > 0:
            recommendations.append({"title": "处理未覆盖用途缺口", "reason": "已确认渠道容量或压力现金偿债预算不足，不能随意提高债务比例。",
                                    "quantification": "尚缺" + _money(unfunded), "action": "将本次支出减少或延后至少" + _money(unfunded) + "，或落实同额真实股东投入/经营回款，并另筹费用。任何新债务须纳入同一预算重算，未确认资金不计入已筹。"})
        service_constraint = next((constraint for constraint in constraint_evidence if constraint["id"] == "debt_service"), None)
        if service_constraint and service_constraint["binding"] and gap > 0:
            recommendations.append({"title": "偿债现金流已成为组合上限", "reason": "低利率短期融资也可能占用更多未来12个月本金偿还预算，不能只按利率从低到高选择渠道。",
                                    "quantification": f"双重压力CFADS{_money(stress_cfads)}÷1.20－存量本息{_money(existing)}，新增本息预算{_money(service_budget)}；组合已使用{_money(service_constraint['used'])}。",
                                    "action": "优先落实已算出的长期容量，核对实际月供与回款日；延长期限、调整还款结构或增加可靠现金来源后重新求解，不能在原方案上直接叠加贷款。"})
        recommendations.append({"title": "单独落实费用资金", "reason": "LP本金覆盖不含另付手续费；未知费率按0占位不等于免费。",
                                "quantification": f"输入假设下一次性费用{_money(fees)}；费用待筹缺口{_money(fee_funding_gap)}。",
                                "action": "索取利息、手续费、担保评估保险及租赁残值等完整条款，并重算实际总成本和资金需求。"})
        if cfads <= 0 or service_budget == 0:
            recommendations.append({"title": "新增债务预算为零", "reason": "非正CFADS或现有债务已耗尽双重压力偿付预算。",
                                    "quantification": f"双重压力CFADS{_money(stress_cfads)}；可分配新增未来12个月本息{_money(service_budget)}。",
                                    "action": "先恢复现金回笼或协商现有还款安排，不用净利润替代CFADS扩大负债。"})
        if high_risks:
            recommendations.insert(0, {"title": "较高风险：仅保留条件预算", "reason": "、".join(high_risks),
                                       "quantification": f"已求得{_money(debt_total)}预算，尚未落实授信。", "action": "先完成人工风险复核与整改，再决定是否申请；数学可行不代表机构受理或获批。"})
        severe = next((scenario for scenario in scenarios if scenario["id"] == "cash_drop_30"), None)
        if severe and severe["gap_to_target"] > 0:
            dscr_label = f"{severe['dscr']:.2f}" if severe["dscr"] is not None else "不适用（偿债本息为0）"
            recommendations.append({"title": "30%现金流下行情景的应对", "reason": "该探索情景未用于主组合约束，用于展示超出设计压力后的脆弱性。",
                                    "quantification": f"整体DSCR为{dscr_label}；达到1.20目标仍缺年度CFADS{_money(severe['gap_to_target'])}。",
                                    "action": "设置现金流滚动复盘：若预计CFADS接近该情景，暂停新增提款，确认客户回款并与债权人协商还款日；不能把年度CFADS缺额直接当作短期周转贷款额度。"})
    recommendations.append({"title": "核对本次自有资金的来源闭环",
                            "reason": "历史货币资金与本次资金计划不直接等同；额外自有资金须已落实、不是借款且不与账面现金重复。",
                            "quantification": internal_source_note,
                            "action": "将本次可投入金额与现金余量及额外资金凭据逐项核对；来源不足时先修正自有投入再重算，来源未完整确认时保留条件预算。"})
    risk_status = "数据待修正或补齐" if errors else "较高风险 · 仅条件预算" if high_risks else "关注风险 · 待人工核验" if concerns else "预算待机构核验"
    status = "暂不形成金额组合" if errors else "无需新增融资" if gap == 0 else "非正CFADS，新增债务为0" if cfads <= 0 else risk_status
    return {
        "version": "1.0", "available": available, "status": status, "risk_status": risk_status,
        "implementation_ready": False, "composition": composition,
        "funding": {"need": need, "internal_used": internal_used, "gap": gap, "debt_total": debt_total,
                    "internal_cash_surplus": cash_surplus, "confirmed_additional_internal_funds": additional_internal,
                    "internal_source_limit": internal_source_limit, "internal_source_excess": internal_source_excess,
                    "internal_source_note": internal_source_note,
                    "net_project_funds": debt_total, "unfunded_gap": unfunded, "fees_due": fees,
                    "total_cash_need": round(need + fees, 2) if available else None,
                    "fee_funding_gap": fee_funding_gap, "total_unfunded_cash": round(unfunded + fee_funding_gap, 2) if available else None,
                    "total_assumed_interest": interest,
                    "note": "本金仅覆盖原用途缺口，一次性费用由企业另筹并单列；未知费用为0占位不代表免收费。预算未落实授信，不是已筹资金。 " + internal_source_note},
        "scenarios": scenarios, "purpose_allocation": purpose_allocation,
        "algorithm": {"name": "四渠道线性约束顶点枚举（字典序双目标）",
                      "objective": ["先最大化对项目外部资金缺口的本金覆盖", "覆盖相同再最小化用户假设下的全期限总利息与一次性费用" if selection_objective == "cost" else "覆盖相同再最小化加息压力下未来12个月还本付息"],
                      "selection_objective": selection_objective,
                      "selection_coefficients": {channel["id"]: weight for channel, weight in zip(channels, stress_factors if selection_objective == "repayment" else cost_weights)},
                      "constraints": constraint_evidence, "checked_candidates": checked,
                      "service_budget": service_budget, "target_dscr": TARGET_DSCR, "planning_stress": {"cash_drop": cash_drop, "rate_up": rate_up},
                      "cost_coefficients": {channel["id"]: weight for channel, weight in zip(channels, cost_weights)},
                      "assumptions": [
                          "只在当前四个候选、已确认基础金额与输入假设内求解；不声称全市场最优或实际最低成本。",
                          f"双重压力为年度CFADS下降{cash_drop:.0%}、利率上行{rate_up*100:g}个百分点，目标DSCR1.20；这些是项目规划假设，不是监管门槛或行业标准。",
                          "应收默认70%、抵质押默认50%、设备租赁默认70%均为可修改规划折扣，不是质押率承诺或自动获批额度。",
                          "仅使用人工确认的已获批未使用独立信用额度、可融资债权、无负担担保基础及真实设备采购金额；不从账面应收、资产总额或税务数据生成这些金额。",
                          "四个融资池必须是独立可叠加的未占用容量，不得互相占用同一授信；抵质押基础须排除用于应收融资的同一债权和租赁设备。未核验独立性前不得实施组合。",
                          "信用和应收限经营用途，设备租赁限设备用途；综合融资子预算合计为需求总额，全部渠道共用一个外部缺口及偿付预算。",
                          "各渠道用等额本息统一比较，新增未来12个月本息=月供×min(合同月数,12)，短合同不重复年化；现有债务采用填报年度本息。真实保理、到期还本或租金结构须按实际合同另测。",
                          "利率、期限和一次性费率为规划输入，默认利率期限沿用用户假设；缺失费用按0占位但真实费用未知。",
                          "本金覆盖不含另付手续费，费用缺口单列；全期限利息不是当期费用缺口，偿付能力通过未来12个月本息约束。",
                          "额外CFADS下降30%仅为探索情景，不参与主组合约束，也不把营收变化自动等同现金流变化。",
                          "本金按分向下取整，分币余量仅在全部约束允许时分配；精确目标相同采用固定渠道顺序消除并列。",
                      ]},
        "recommendations": recommendations, "risk_flags": list(dict.fromkeys(errors + flags)),
        "alternatives": alternatives, "industry": _industry(data, profile),
        "repayment_note": "新增未来12个月本息=月供×min(合同月数,12)，短合同仅计算其实际期数；不假定到期续贷。所有金额方案仅为条件预算，须核对实际还款日期及合同结构。",
    }
