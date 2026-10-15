"""Auditable financing budgets built from the task's locked financial inputs.

The policy below is a project demonstration method, not an underwriting policy.
No lender product, appraisal value, advance rate or market quotation is inferred.
"""
from __future__ import annotations

from copy import deepcopy
import math
from numbers import Real
import re
from typing import Any, Mapping, Sequence

TARGET_DSCR = 1.20
STRESS_CASH_DROP = 0.20
STRESS_RATE_UP = 0.01
MAX_AMOUNT = 1e15
CORE_FIELDS = ("total_assets", "total_liabilities", "current_assets", "current_liabilities", "revenue", "net_profit")

INDUSTRIES = (
    {
        "id": "construction", "name": "工程与建筑", "keywords": ("工程", "建筑", "施工", "装饰", "基建"),
        "pain_points": ["垫资与工程计量、验收、结算时点可能错配", "进度款、质保金和争议款需分别核验可回收性"],
        "financing_tools": ["对已确权的工程应收款核验债权融资条件", "按可核验进度及回款预算比较经营周转融资"],
        "repayment_match": "围绕合同计量、验收与回款节点设计还款；争议款和未确权工程量不作为确定还款来源。",
        "verification_materials": ["工程合同、计量确认及验收记录", "进度款与质保金明细", "付款方确权及结算回款安排", "项目资金使用与垫资预算"],
    },
    {
        "id": "agriculture_food", "name": "农业与食品", "keywords": ("农业", "食品", "农产品", "养殖", "种植", "粮", "牧", "渔"),
        "pain_points": ["季节性采购、生产及销售可能形成集中资金缺口", "存货保质期、损耗与价格波动会影响可回收现金"],
        "financing_tools": ["按采购与销售季节比较经营周转融资", "在债权可核验时比较应收账款融资", "设备采购另行比较真实设备融资租赁"],
        "repayment_match": "依据采购季、销售季及回款安排测算，避开仅按全年利润推定旺季偿债能力。",
        "verification_materials": ["季节性采购销售与回款预算", "存货批次、库龄及损耗记录", "供应与销售合同", "适用的经营许可及产品质量资料"],
    },
    {
        "id": "commerce", "name": "商贸与流通", "keywords": ("商贸", "贸易", "批发", "零售", "电商", "电子商务", "经销", "流通"),
        "pain_points": ["备货、库存周转与客户账期可能占用流动资金", "客户集中、退货和供应商结算条款会影响现金回笼"],
        "financing_tools": ["按订单备货与回款安排比较经营周转融资", "对真实且可转让的贸易债权核验应收融资条件"],
        "repayment_match": "使提款及还款匹配进货、销售、退货和客户回款周期，避免以短期周转资金承担长期投资。",
        "verification_materials": ["采购订单与销售合同", "库存库龄、退货与滞销记录", "主要客户账期及对账确认", "供应商结算条件与回款流水"],
    },
    {
        "id": "software_technology", "name": "软件与科技服务", "keywords": ("软件", "信息技术", "信息服务", "互联网", "人工智能", "数字技术", "科技服务", "saas"),
        "pain_points": ["研发和人员支出可能先于项目验收及订阅回款", "轻资产企业的账面无形资产不能直接视为可用担保额度"],
        "financing_tools": ["按已签合同、验收和回款资料比较经营周转融资", "有可核验债权时比较应收融资", "研发等长周期投入可核验股东投入与分阶段预算"],
        "repayment_match": "匹配验收、订阅续费及回款节点；尚未签约的销售预测和研发成果不等于可用于偿债现金。",
        "verification_materials": ["客户合同、验收节点及回款记录", "订阅或维护收入与续费明细", "人员及研发支出预算", "知识产权权属与已有权利负担资料"],
    },
    {
        "id": "manufacturing", "name": "制造业", "keywords": ("制造", "精密", "机械", "工业", "装备", "生产", "加工", "电子"),
        "pain_points": ["原材料、在制品与客户账期可能形成现金转换周期缺口", "设备投入回收期可能长于经营周转贷款期限"],
        "financing_tools": ["可核验应收债权融资与经营周转融资互斥比较", "设备购置优先比较真实设备租赁与有条件抵押融资"],
        "repayment_match": "周转融资匹配采购、生产、交付与回款；设备融资需另核验投产时间和设备带来的现金流。",
        "verification_materials": ["主要订单、购销合同与验收凭证", "应收账龄、客户集中度及回款计划", "原材料与在制品库龄", "设备报价、权属与投产现金流预算"],
    },
    {
        "id": "services", "name": "一般服务业", "keywords": ("服务", "咨询", "餐饮", "酒店", "旅游", "物流", "教育", "文旅"),
        "pain_points": ["人员、场地等固定现金支出可能早于服务回款", "预收款、退款义务和季节性客流需分别评估"],
        "financing_tools": ["按服务合同和现金回笼比较经营周转融资", "对已履约且可确认的应收款核验债权融资条件"],
        "repayment_match": "将还款预算与实际服务履约和收款周期对齐；预收款需扣除后续履约及退款所需资金。",
        "verification_materials": ["服务合同、履约及收款记录", "预收款与退款义务明细", "人员、租赁等固定现金支出预算", "季节性经营流水及适用资质"],
    },
)
GENERIC_INDUSTRY = {
    "id": "generic", "name": "通用企业场景", "pain_points": ["经营投入、回款时点和偿债安排可能错配", "当前行业未匹配细分场景，需由经办人补充业务周期资料"],
    "financing_tools": ["按真实用途比较经营周转、可核验债权融资或设备融资", "不足部分核验股东投入、回款改善或缩减投入的可行性"],
    "repayment_match": "以合同、回款与现金支出计划确定还款节点；当前规则不代表覆盖所有行业。",
    "verification_materials": ["业务合同与资金用途明细", "经营周期及回款预算", "现有债务与担保清单", "主要支出和备用资金安排"],
}


def _finite(value: Any, low: float = -MAX_AMOUNT, high: float = MAX_AMOUNT) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real) or not low <= value <= high:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _amount(value: Any) -> float | None:
    number = _finite(value, 0)
    return round(number, 2) if number is not None else None


def annual_annuity_factor(rate: float, months: int) -> float:
    """Annualized monthly annuity payment per unit principal, with stable arithmetic."""
    if not 0 <= rate <= 2 or not 1 <= months <= 120 or int(months) != months:
        raise ValueError("测算年利率或期限超出允许范围")
    monthly_rate = rate / 12
    return 12 / months if monthly_rate == 0 else monthly_rate * 12 / -math.expm1(-months * math.log1p(monthly_rate))


def _industry(data: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    text = str(profile.get("industry") or data.get("industry") or "").strip().casefold()
    for rule in INDUSTRIES:
        matched = next((keyword for keyword in rule["keywords"] if keyword in text), None)
        if matched:
            return dict(deepcopy({key: value for key, value in rule.items() if key != "keywords"}), input_label=text, matched_keyword=matched,
                        note="依据填报行业关键词选择准备资料，不推断企业实际经营事实或行业授信标准。")
    return dict(deepcopy(GENERIC_INDUSTRY), input_label=text, matched_keyword=None,
                note="当前只覆盖六类示例场景及通用流程；未匹配行业需人工补充专属规则。")


def _scenario(cfads: float, existing: float, principal: float, rate: float, months: int) -> dict[str, Any]:
    new_service = principal * annual_annuity_factor(rate, months)
    total = existing + new_service
    return {"cfads": cfads, "existing_annual_service": existing, "new_annual_service": new_service,
            "total_annual_service": total, "dscr": cfads / total if total > 0 else None}


def _capacity(cfads: float, existing: float, rate: float, months: int, gap: float) -> tuple[float, float]:
    unconstrained = max(0.0, cfads / TARGET_DSCR - existing) / annual_annuity_factor(rate, months)
    # Round down so a currency rounding cannot move stress DSCR below the target.
    capacity = math.floor(unconstrained * 100) / 100
    return capacity, min(capacity, gap)


def _route_ranking(profile: Mapping[str, Any], routes: Sequence[Mapping[str, Any]], industry: Mapping[str, Any]) -> list[dict[str, Any]]:
    equipment = profile.get("purpose") == "设备购置"
    supplied = {route.get("id"): route for route in routes if isinstance(route, Mapping)}
    names = {"working": "经营周转贷款", "receivable": "应收账款融资", "secured": "抵质押融资", "leasing": "设备融资租赁"}
    if equipment:
        order = ("leasing", "secured", "receivable", "working")
    elif profile.get("receivables") == "可提供":
        order = ("receivable", "working", "secured", "leasing")
    else:
        order = ("working", "receivable", "secured", "leasing")
    result = []
    for route_id in order:
        route = supplied.get(route_id, {})
        reasons, status = [], "待机构核验"
        if route_id == "working":
            if equipment:
                status = "用途不符"
                reasons.append("本次为设备购置，经营周转贷款不作为设备投资主方案。")
            else:
                reasons.append("按填报的经营周转或订单备货用途准备，不假设企业已具备信用授信。")
        elif route_id == "receivable":
            condition = profile.get("receivables", "未确认")
            if equipment:
                status = "用途关联待核验"
                reasons.append("设备投入优先比较与租赁物或担保资产对应的融资；债权融资的合同用途需另核验。")
            elif condition == "无":
                status = "受阻"
                reasons.append("企业填报无可核验的应收债权。")
            elif condition != "可提供":
                status = "条件方案"
                reasons.append("应收债权尚未确认，核验前不作为可执行主方案。")
            else:
                reasons.append("企业填报可提供债权，仍需确权、账龄、回款与既有权利负担核验。")
            reasons.append("不以账面应收余额推算质押率或可获批额度。")
        elif route_id == "secured":
            condition = profile.get("collateral", "未确认")
            if condition == "无":
                status = "受阻"
                reasons.append("企业填报无可用抵质押资产。")
            elif condition != "可提供":
                status = "条件方案"
                reasons.append("抵质押资产未确认，须先补齐权属与负担资料。")
            else:
                reasons.append("企业填报可提供资产，须取得权属、既有负担与机构接受条件。")
            reasons.append("不把资产总额、净资产或账面价值视为可贷额度。")
        elif not equipment:
            status = "本次用途不匹配"
            reasons.append("当前不是设备购置，不假设已有可融资的真实租赁物。")
        else:
            reasons.append("设备购置优先围绕真实设备合同、交付和投产现金流比较租赁。")
            reasons.append("当前偿付预算用等额本息作统一比较基准，不能替代实际租金结构。")
        if not route:
            status = "工具依据缺失"
            reasons.append("本次路径工具未提供此路径的条件与资料，不能直接实施。")
        result.append({"route_id": route_id, "name": str(route.get("name", names[route_id])), "rank": len(result) + 1,
                       "status": status, "reasons": reasons, "source": route.get("source"),
                       "conditions": list(route.get("conditions", [])), "materials": list(route.get("materials", [])),
                       "repayment_match": industry["repayment_match"]})
    return result


def build_financing_plan(data: Mapping[str, Any], profile: Mapping[str, Any], quality: Mapping[str, Any],
                         risk: Mapping[str, Any], simulation: Mapping[str, Any], routes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a decision, alternative budgets and explicit gates using one snapshot.

    ``debt_capacity`` is a mathematical cash-flow limit, never an approved loan.
    ``non_debt_gap`` is uncommitted money still to arrange; alternatives are
    mutually exclusive and never increase the single aggregate debt budget.
    """
    need, internal = _amount(profile.get("amount")), _amount(profile.get("internal_funds"))
    rate = _finite(profile.get("assumed_rate"), 0, 1)
    term = _finite(profile.get("months"), 1, 120)
    months = int(term) if term is not None and int(term) == term else None
    purpose_valid = profile.get("purpose") in ("经营周转", "订单备货", "设备购置")
    inputs_ready = need is not None and internal is not None and rate is not None and months is not None and purpose_valid
    internal_used = min(need, internal) if need is not None and internal is not None else None
    gap = round(max(0.0, need - internal), 2) if need is not None and internal is not None else None
    cfads = _finite(data.get("cash_flow_available_for_debt_service"))
    existing = _finite(data.get("scheduled_debt_service"), 0)
    annual = bool(re.fullmatch(r"20\d{2}(?:年度|年|-12-31)?", str(data.get("report_period") or "").strip()))
    core_missing = [field for field in CORE_FIELDS if _finite(data.get(field)) is None]
    contradictions = []
    for low, high in (("current_assets", "total_assets"), ("current_liabilities", "total_liabilities"), ("quick_assets", "current_assets"), ("cash_and_equivalents", "current_assets")):
        lower, upper = _finite(data.get(low)), _finite(data.get(high))
        if lower is not None and upper is not None and lower > upper:
            contradictions.append(f"{low}大于{high}")
    data_blocked = bool(quality.get("blocked") or quality.get("invalid") or quality.get("issues") or contradictions)
    data_missing = bool(core_missing or quality.get("core_missing") or not quality.get("period_known"))
    data_ready = not data_blocked and not data_missing
    simulation_available = simulation.get("available") is True
    simulation_gap = _finite(simulation.get("gap"), 0)
    simulation_consistent = simulation_gap is not None and gap is not None and math.isclose(simulation_gap, gap, abs_tol=0.011, rel_tol=1e-12)
    cash_ready = cfads is not None and cfads > 0 and existing is not None
    calculation_available = inputs_ready and data_ready and annual and cash_ready and simulation_available and simulation_consistent
    high_risks = [str(dimension.get("label", key)) for key, dimension in risk.get("dimensions", {}).items()
                  if isinstance(dimension, Mapping) and dimension.get("risk_level") == "较高"]
    risk_known = bool(risk.get("dimensions"))
    risk_ready = risk_known and not high_risks
    industry = _industry(data, profile)
    ranking = _route_ranking(profile, routes, industry)
    eligible = [route for route in ranking if route["status"] == "待机构核验"]
    chosen = eligible[0] if eligible else next((route for route in ranking if route["status"] == "条件方案"), ranking[0])
    route_ready = chosen["status"] == "待机构核验"
    capacity, budget_debt = (None, None)
    if calculation_available:
        capacity, budget_debt = _capacity(cfads * (1 - STRESS_CASH_DROP), existing, rate + STRESS_RATE_UP, months, gap)
    debt_allowed = calculation_available and risk_ready and route_ready
    proposed = budget_debt if debt_allowed else None
    if gap == 0 and inputs_ready:
        proposed = 0.0
    pending = round(gap - proposed, 2) if gap is not None and proposed is not None else None

    reasons = []
    if not inputs_ready:
        code, title = "invalid_input", "暂停：融资需求或测算参数无效"
        reasons.append("需求金额、自有资金、整数期限、假设利率和用途须先确认。")
    elif gap == 0:
        code, title = "no_gap", "暂无新增融资缺口"
        reasons.append("填报自有资金可覆盖需求；须核验资金可支配性并保留日常经营资金。")
    elif data_blocked:
        code, title = "correct_data", "暂停：先修正数据口径"
        reasons.extend(str(item) for item in quality.get("issues", []))
        reasons.extend(contradictions)
        reasons.append("存在无效字段或金额关系矛盾，当前不形成新增债务金额建议。")
    elif data_missing or not annual or not simulation_available or not simulation_consistent:
        code, title = "supplement_data", "暂停：补齐年度偿付依据"
        reasons.append("需同一年度的核心财务数据、CFADS和现有年度偿债本息，以及一致的压力测试输入。")
    elif not cash_ready:
        code, title = "pause_cash_flow", "暂停：先恢复可用于偿债现金流"
        reasons.append("CFADS缺失、非正值或现有偿债本息无效，不能用净利润替代现金偿债能力。")
    elif not risk_ready:
        code, title = "risk_review", "暂停：优先整改并复核风险"
        reasons.append("较高风险维度：" + "、".join(high_risks) if high_risks else "风险工具依据不完整。")
        reasons.append("即使数学偿债容量为正，也不等于当前可以提交的融资方案。")
    elif not route_ready:
        code, title = "conditional", "暂停：主路径条件尚未落实"
        reasons.extend(chosen["reasons"])
    elif proposed == 0:
        code, title = "no_capacity", "暂不安排新增债务，先补足非债务资金"
        reasons.append("在本项目压力假设及DSCR目标下，现有债务已占满新增偿债预算。")
    elif pending > 0:
        code, title = "resize", "缩减新增债务，并落实剩余资金来源"
        reasons.append("需求缺口超过压力情景可承受新增债务预算，不应把整个缺口直接作为借款金额。")
    else:
        code, title = "review", "按预算主方案进入人工核验"
        reasons.append("在用户输入和本项目压力假设下，预算可覆盖需求缺口；金额与路径仍须由机构核验。")
    summary = reasons[0]
    if proposed is not None and gap and proposed > 0:
        summary += f" 当前请求期限{months}个月，新增债务预算上限{proposed / 1e8:,.6f}亿元，尚未落实资金缺口{pending / 1e8:,.6f}亿元。"

    gates = [
        {"id": "inputs", "label": "需求与用途参数", "status": "通过" if inputs_ready else "未通过",
         "detail": "金额来自填报需求与自有资金；期限和利率为用户假设。", "evidence": {"need": need, "internal_available": internal, "months": months, "assumed_rate": rate, "purpose": profile.get("purpose")}},
        {"id": "data", "label": "数据完整性与一致性", "status": "通过" if data_ready else "未通过" if data_blocked else "待补充",
         "detail": "核心字段、金额关系及报告期须先核对；通过不表示已审计。", "evidence": {"core_missing": core_missing, "invalid": list(quality.get("invalid", [])), "issues": list(quality.get("issues", [])) + contradictions}},
        {"id": "annual", "label": "年度偿付口径", "status": "通过" if annual else "待补充",
         "detail": "不把季度或中期现金流自动年化。", "evidence": {"report_period": data.get("report_period"), "annual": annual}},
        {"id": "cash", "label": "真实现金偿债输入", "status": "通过" if cash_ready else "未通过" if cfads is not None and cfads <= 0 else "待补充",
         "detail": "须提供正的年度CFADS与非负的现有年度偿债本息，不使用净利润代替。", "evidence": {"cfads": cfads, "existing_annual_service": existing}},
        {"id": "simulation", "label": "压力工具与快照一致", "status": "通过" if simulation_available and simulation_consistent else "待补充",
         "detail": "以同一需求快照重算固定20%现金流下降与1个百分点利率上行情景。", "evidence": {"available": simulation_available, "same_gap": simulation_consistent}},
        {"id": "risk", "label": "较高风险复核", "status": "通过" if risk_ready else "未通过" if high_risks else "待补充",
         "detail": "较高风险先整改复核，数学预算不能覆盖风险阻断。", "evidence": {"high_risk_dimensions": high_risks}},
        {"id": "route", "label": "主路径必要条件", "status": "待机构核验" if route_ready else "未通过",
         "detail": "企业勾选可提供仅为填报条件，交易真实性、权属和机构接受条件仍需核验。", "evidence": {"route_id": chosen["route_id"], "route_status": chosen["status"]}},
    ]

    repayment: dict[str, Any] = {
        "available": calculation_available, "budget_only": not debt_allowed,
        "basis": "现金流数学预算，不代表审批、贷款报价或实际租赁还款安排。风险受阻时仅保留数学比较，不作为可提交方案。",
        "months": months, "assumed_rate": rate, "stress_rate": rate + STRESS_RATE_UP if rate is not None else None,
        "annual_annuity_factor": annual_annuity_factor(rate + STRESS_RATE_UP, months) if calculation_available else None,
        "capacity_formula": "可承受新增债务上限 = max(0, 压力CFADS / 1.20 - 现有年度偿债本息) / 压力年化等额本息系数；新增债务预算再取与需求缺口的较小值。",
        "budget_principal": budget_debt, "base": None, "stress": None, "monthly_payment": None,
        "total_interest": None, "total_principal_interest": None,
        "cost_note": "仅按用户假设利率作等额本息估算；总额使用未舍入月供计算。手续费、担保费、评估费、保险及租赁结构费用未知，不能据此声称综合融资成本。",
    }
    if calculation_available:
        monthly_payment = budget_debt * annual_annuity_factor(rate, months) / 12
        repayment.update(base=_scenario(cfads, existing, budget_debt, rate, months),
                         stress=_scenario(cfads * (1 - STRESS_CASH_DROP), existing, budget_debt, rate + STRESS_RATE_UP, months),
                         monthly_payment=monthly_payment, total_interest=round(max(0.0, monthly_payment * months - budget_debt), 2),
                         total_principal_interest=round(monthly_payment * months, 2))

    primary = {"route_id": chosen["route_id"], "title": chosen["name"] if gap != 0 else "自有资金覆盖，不新增债务",
               "category": "主方案", "status": title, "amount": proposed,
               "execution_status": "准备方案，条件待核验，授信未落实" if gap else "无需新增债务；自有资金可支配性待核验",
               "reason": "；".join(chosen["reasons"]) if gap != 0 else reasons[0],
               "conditions": chosen["conditions"] + ["完成全部财务及风险决策门槛", "核验实际报价、合同用途及还款节点", "剩余资金来源落实后再实施完整投入"],
               "materials": list(dict.fromkeys(chosen["materials"] + industry["verification_materials"])),
               "repayment_match": industry["repayment_match"],
               "amount_basis": "同一新增债务预算只采用一条主路径；主备路径互斥，不将预算重复叠加。"}
    alternatives = []
    for route in [route for route in ranking if route["route_id"] != chosen["route_id"]][:2]:
        suitable = route["status"] == "待机构核验"
        alternatives.append({"route_id": route["route_id"], "title": route["name"], "category": "替代融资路径" if suitable else "条件或受阻路径",
                             "status": "互斥备选 · 待机构核验" if suitable and debt_allowed and gap else route["status"],
                             "amount": proposed if suitable and debt_allowed and gap else None,
                             "reason": "；".join(route["reasons"]), "why_not_primary": "当前用途与已填报条件的准备顺序靠后；若切换则替代主路径，不增加总债务预算。",
                             "conditions": route["conditions"], "materials": route["materials"], "repayment_match": industry["repayment_match"],
                             "amount_basis": "与主方案互斥，使用同一个新增债务预算；具体合同费用未知，暂不能判断哪条路径成本最低。"})
    alternatives.append({"route_id": "non_debt", "title": "分阶段投入与非债务资金补足", "category": "资金结构替代",
                         "status": "资金来源待确认" if gap else "按需核验备用资金", "amount": pending if pending is not None else gap,
                         "reason": "剩余缺口只能列为尚未落实资金，不能当作已筹资金或虚构股东承诺。",
                         "why_not_primary": "若新增债务被阻断，先验证缩减采购、加速真实回款或股东投入；这些措施尚未落实。",
                         "conditions": ["股东投入须有真实出资意愿与到账安排", "加速回款须有客户确认且不得重复计入CFADS或自有资金", "压缩或分批采购须取得业务可行性及供应商确认"],
                         "materials": ["股东资金来源与投入安排（如选择）", "客户确认的回款计划（如选择）", "分阶段采购与投资预算（如选择）"],
                         "repayment_match": "非债务资金并不自动存在；若改用股东借款，应作为新增债务重新测算。",
                         "amount_basis": "表示待落实的剩余缺口，不计入已筹资金。"})

    term_comparison = []
    for candidate in sorted(set([months] + [12, 24, 36, 60]) - {None}):
        cap, candidate_budget = (None, None)
        if calculation_available:
            cap, candidate_budget = _capacity(cfads * (1 - STRESS_CASH_DROP), existing, rate + STRESS_RATE_UP, candidate, gap)
        candidate_proposed = candidate_budget if debt_allowed else 0.0 if gap == 0 and inputs_ready else None
        long_working = profile.get("purpose") != "设备购置" and candidate >= 60
        candidate_base = _scenario(cfads, existing, candidate_budget, rate, candidate) if calculation_available else None
        candidate_stress = _scenario(cfads * (1 - STRESS_CASH_DROP), existing, candidate_budget, rate + STRESS_RATE_UP, candidate) if calculation_available else None
        term_comparison.append({"months": candidate, "selected": candidate == months,
                                "debt_capacity": cap, "proposed_debt": candidate_proposed,
                                "remaining_gap": round(gap - candidate_proposed, 2) if candidate_proposed is not None else None,
                                "base_dscr": candidate_base["dscr"] if candidate_base else None,
                                "stress_dscr": candidate_stress["dscr"] if candidate_stress else None,
                                "monthly_payment": candidate_budget * annual_annuity_factor(rate, candidate) / 12 if calculation_available else None,
                                "total_interest": round(max(0.0, candidate_budget * annual_annuity_factor(rate, candidate) / 12 * candidate - candidate_budget), 2) if calculation_available else None,
                                "status": "输入不足或矛盾，不给金额方案" if not calculation_available else "仅数学比较，风险或条件阻断" if not debt_allowed else "仅长期假设比较，周转周期待核验" if long_working else "预算待核验",
                                "note": "延长期限可降低年化偿付但可能增加总利息；须核验真实业务周期、用途及机构可受理期限，不自动推荐最长贷款。"})

    return {
        "version": "1.0", "status": title,
        "decision": {"code": code, "title": title, "summary": summary, "reasons": reasons, "debt_allowed": debt_allowed and bool(gap)},
        "assumptions": {"target_dscr": TARGET_DSCR, "cash_drop": STRESS_CASH_DROP, "rate_up": STRESS_RATE_UP,
                        "source": "项目演示决策假设；非监管门槛、银行准入或行业标准。",
                        "payment_method": "等额本息月供×12的年化比较口径；不足12个月不代表完整年度实际还款总额。",
                        "allocation_rule": "主备融资路径互斥；所有路径共用一个新增债务预算。"},
        "gates": gates,
        "funding": {"need": need, "internal_available": internal, "internal_used": internal_used, "gap": gap,
                    "debt_capacity": capacity, "proposed_debt": proposed, "non_debt_gap": pending,
                    "allocated_total": round(internal_used + proposed, 2) if internal_used is not None and proposed is not None else None,
                    "unallocated_gap": pending if pending is not None else gap,
                    "note": "debt_capacity为现金流数学容量，不是可获批额度；proposed_debt为待核验债务预算；allocated_total仅为自有资金与该预算之和。non_debt_gap尚未落实，不计入覆盖额。"},
        "primary": primary, "alternatives": alternatives, "route_ranking": ranking,
        "repayment": repayment, "term_comparison": term_comparison, "industry": industry,
        "schedule": [
            {"phase": "第1阶段 · 数据核对", "owner": "财务负责人", "actions": ["核对同一年度报表、CFADS构成与现有本息清单", "修正决策门槛中的缺失与矛盾", "核验自有资金可支配性"], "exit_condition": "输入一致且现金偿债依据可核验；未通过则停留本阶段。"},
            {"phase": "第2阶段 · 风险与路径核验", "owner": "财务负责人 / 融资经办人", "actions": ["对较高风险形成整改说明并重新计算", "准备主路径及行业专属材料", "确认债权、担保资产或设备合同的真实性与权利负担"], "exit_condition": "风险复核通过且主路径条件具备；未通过不提交肯定金额。"},
            {"phase": "第3阶段 · 结构与合同比较", "owner": "企业负责人 / 融资经办人", "actions": ["用实际报价及还款节点替换假设后重新测算", "比较请求期限及备选期限的现金流与总成本", "落实剩余缺口或调整采购、投资规模"], "exit_condition": "完整资金闭合、用途合规且重新计算的压力偿付可接受；备选替换主方案而非叠加。"},
            {"phase": "第4阶段 · 申请与跟进", "owner": "企业负责人", "actions": ["经人工确认后向选定机构提交资料，由机构独立审查", "按业务周期跟踪回款、用途和偿债资金", "发生退出触发时暂停提款并重算方案"], "exit_condition": "实际合同、资金到账与还款安排均有记录；不把方案生成视作授信完成。"},
        ],
        "exit_triggers": [
            {"id": "coverage", "trigger": "更新真实现金流、债务或合同利率后，压力DSCR低于项目假设1.20", "action": "暂停当前债务预算，缩额、调整投入或重核期限后重新测算。"},
            {"id": "data", "trigger": "报表期间、金额或CFADS核验出现矛盾，或CFADS非正", "action": "停止输出肯定融资金额，先修正资料或恢复现金偿债能力。"},
            {"id": "rights", "trigger": "债权不能确权、担保存在未披露负担或设备合同不能验证", "action": "退出对应路径，核验互斥备选；不能沿用原路径额度假设。"},
            {"id": "funding", "trigger": "剩余非债务资金未落实，或回款计划不能兑现", "action": "暂停完整投入，核验分阶段实施；不将待确认资金写作已筹资金。"},
            {"id": "cycle", "trigger": "实际回款与还款节点不匹配，或用途、期限条件不被机构接受", "action": "重做现金流时序与期限比较，必要时退出融资申请。"},
        ],
        "limitations": [
            "本方案来自用户或模拟输入，未连接征信、税务、银行报价或真实授信系统。",
            "20%现金流下降、利率上行1个百分点及DSCR1.20均为本项目演示假设，须经真实业务校准。",
            "债务上限仅由年度现金流数学预算推导，不推断应收质押率、担保估值、银行额度或获批概率。",
            "需求总额减可用自有资金仅为用户申报项目缺口，不是银行核定的流动资金贷款需求；尚缺完整营运周期、现有流动资金贷款及其他营运融资等核定资料。",
            "可提供应收债权只是待核验条件；保理或质押法律结构、确权与合同限制未选定，不据账面应收余额自动核定额度。",
            "等额本息是统一比较基准；租赁设备、期限、残值与租金结构未知，须与到期还本及季节性还款一样按实际合同另测，不能直接沿用此月供。",
            "主备方案金额互斥；待落实股东投入、加速回款及压缩采购均不计为已筹资金，也不自动增加CFADS。",
            "行业适配仅覆盖六类示例及通用流程，不代表覆盖全部行业或采用行业授信标准。",
        ],
    }
