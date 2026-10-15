"""Financial analysis and constrained financing portfolio tools."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import html
import io
import json
import math
import re
from numbers import Real
from time import perf_counter
from typing import Any, Callable, Mapping
import uuid
import zipfile

from finbridge.finance import METRIC_DEFINITIONS, calculate_financial_ratios
from finbridge.risk import analyze_financial_risk
from finbridge.data import FIELD_CATALOG
from finbridge.analysis import calculate_deep_metrics, enriched_financial_data, financial_drivers, EXTRA_METRICS
from finbridge.portfolio import build_financing_portfolio
from finbridge.decision import annual_annuity_factor
from finbridge.industry_context import context_placeholder, context_markdown
from finbridge.market_rules import effective_portfolio

LABELS = {
    "company_name": "企业名称", "report_period": "报告期", "total_assets": "资产总额",
    "total_liabilities": "负债总额", "current_assets": "流动资产", "current_liabilities": "流动负债",
    "quick_assets": "速动资产", "cash_and_equivalents": "货币资金", "revenue": "营业收入",
    "net_profit": "净利润", "gross_profit": "毛利", "cost_of_goods_sold": "营业成本",
    "ebit": "息税前利润", "interest_expense": "利息费用", "beginning_total_assets": "期初总资产",
    "ending_total_assets": "期末总资产", "beginning_equity": "期初所有者权益", "ending_equity": "期末所有者权益",
    "beginning_accounts_receivable": "期初应收账款", "ending_accounts_receivable": "期末应收账款",
    "beginning_inventory": "期初存货", "ending_inventory": "期末存货", "accounts_receivable": "应收账款",
    "inventory": "存货", "operating_cash_flow": "经营活动现金流量净额",
    "cash_flow_available_for_debt_service": "可用于偿债现金流（CFADS）",
    "scheduled_debt_service": "现有年度偿债本息", "prior_revenue": "上期营业收入", "prior_net_profit": "上期净利润",
    "financing_need": "资金需求总额", "available_internal_funds": "可用自有资金",
    "current_ratio": "流动比率", "quick_ratio": "速动比率", "cash_ratio": "货币资金总额 / 流动负债",
    "debt_to_asset_ratio": "资产负债率", "interest_coverage": "利息保障倍数",
    "return_on_assets": "总资产收益率", "return_on_equity": "净资产收益率", "net_profit_margin": "净利润率",
    "gross_profit_margin": "毛利率", "receivables_turnover": "应收账款周转率", "receivables_days": "应收账款周转天数",
    "inventory_turnover": "存货周转率", "inventory_days": "存货周转天数", "total_asset_turnover": "总资产周转率",
    "operating_cash_flow_to_net_profit": "经营现金流 / 净利润",
    "operating_cash_flow_to_current_liabilities": "经营现金流 / 流动负债",
    "operating_cash_flow_margin": "经营现金流率", "revenue_growth": "营收同比", "net_profit_growth": "利润同比",
    "dscr": "现有债务偿付覆盖率", "interest_burden": "利息负担率", "financing_gap": "外部融资缺口",
}
CORE_FIELDS = ("total_assets", "total_liabilities", "current_assets", "current_liabilities", "revenue", "net_profit")
LABELS.update({key: definition["label"] for key, definition in FIELD_CATALOG.items()})
LABELS.update({key: definition[0] for key, definition in EXTRA_METRICS.items()})
DATA_FIELDS = tuple(key for key, definition in FIELD_CATALOG.items() if definition["unit"] in {"元", "%", "月"})
GOALS = {
    "融资组合": "根据企业财务数据、渠道容量和压力偿债约束计算融资组合。",
    "风险分析": "定位现金流、周转和债务风险，量化资金缺口与改善措施。",
    "方案比较": "比较融资组合的假设成本、偿付负担与压力情景。",
}
KNOWLEDGE = [
    {"id": "KB-001", "title": "流动资金贷款管理办法", "publisher": "国家金融监督管理总局", "date": "2024-02-02",
     "url": "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=1151066&generaltype=1&itemId=861",
     "scope": "流动资金贷款用途与需求核验", "text": "流动资金贷款用于日常生产经营周转，金额与期限需结合经营规模、资金循环和真实需求核验，扣除自有资金、现有流贷及其他营运融资。固定资产相关需求须另核用途与特别条款；申请额减自有资金不等于机构核定额度。", "tags": ["流动资金", "周转", "用途"]},
    {"id": "KB-002", "title": "动产和权利担保统一登记办法", "publisher": "中国人民银行（湖南省政府转载）", "date": "2021-12-28",
     "url": "https://www.hunan.gov.cn/zqt/zcsd/202205/t20220530_24763381.html",
     "scope": "应收账款与动产担保核验", "text": "应收账款质押、融资租赁等纳入统一登记。登记机构不对登记内容进行实质审查，仍需核验权属与交易真实性。", "tags": ["应收账款", "抵押", "设备", "租赁"]},
    {"id": "KB-003", "title": "国务院关于实施动产和权利担保统一登记的决定", "publisher": "国务院", "date": "2020-12-22",
     "url": "https://app.www.gov.cn/govdata/gov/202012/29/466467/article.html",
     "scope": "担保登记范围", "text": "生产设备等动产抵押、应收账款质押、保理、融资租赁等纳入统一登记范围，登记内容由当事人负责。", "tags": ["担保", "抵押", "保理", "租赁"]},
    {"id": "KB-004", "title": "金融租赁公司融资租赁业务管理办法", "publisher": "国家金融监督管理总局（国务院网站转载）", "date": "2025-12-04",
     "url": "https://app.www.gov.cn/govdata/gov/202512/06/540892/article.html",
     "scope": "金融租赁公司的设备租赁核验", "text": "金融租赁公司需核验租赁物真实性、权属与价值、承租人的现金流覆盖。期限结合回收周期且不超过剩余使用年限；实际租金结构与综合成本须在合同中确认。该办法适用于获批金融租赁公司，不泛化至全部商业租赁机构。", "tags": ["设备", "租赁", "现金流"]},
]


def clean_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Produce a finite JSON snapshot without sharing mutable user data."""
    result = {}
    for key, value in data.items():
        if key in {"public_provenance","financial_history"} and isinstance(value,(dict,list)):
            result[str(key)] = deepcopy(value)
        elif isinstance(value, Real) and not isinstance(value, bool):
            result[str(key)] = float(value) if math.isfinite(float(value)) else None
        elif value is None or isinstance(value, (str, bool)):
            result[str(key)] = value
        else:
            result[str(key)] = str(value)
    return result


def fingerprint(data: Mapping[str, Any], profile: Mapping[str, Any]) -> str:
    payload = json.dumps([clean_data(data), clean_data(profile)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "待补充"
    if unit == "%":
        return f"{value:.1%}"
    if unit == "元":
        return f"{value / 1e8:,.6f} 亿元"
    return f"{value:,.2f} {unit}".strip()


def check_data(data: Mapping[str, Any]) -> dict[str, Any]:
    missing, invalid, issues = [], [], []
    signed = {"net_profit", "prior_net_profit", "operating_cash_flow", "cash_flow_available_for_debt_service", "ebit", "gross_profit", "operating_profit", "income_tax_expense", "beginning_equity", "ending_equity", "projected_revenue_growth"}
    for field in DATA_FIELDS:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
        elif isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or abs(value) > 1e15 or (value < 0 and field not in signed):
            invalid.append(field)
        elif FIELD_CATALOG[field]["unit"] == "%" and not (-1 if field == "projected_revenue_growth" else 0) <= value <= (100 if field == "projected_revenue_growth" else 1):
            invalid.append(field)
        elif FIELD_CATALOG[field]["unit"] == "月" and (not 1 <= value <= 120 or int(value) != value):
            invalid.append(field)
    for lower, upper in (("current_assets", "total_assets"), ("current_liabilities", "total_liabilities"), ("quick_assets", "current_assets"), ("cash_and_equivalents", "current_assets"), ("restricted_cash", "cash_and_equivalents"), ("receivables_overdue", "ending_accounts_receivable"), ("receivables_over_90_days", "receivables_overdue"), ("eligible_receivables", "ending_accounts_receivable"), ("maintenance_capex", "capital_expenditure")):
        a, b = data.get(lower), data.get(upper)
        if lower not in invalid + missing and upper not in invalid + missing and a > b:
            issues.append(f"{LABELS[lower]}大于{LABELS[upper]}，请核对口径")
    for ending, total in (("ending_total_assets", "total_assets"),):
        if ending not in invalid + missing and total not in invalid + missing and not math.isclose(data[ending], data[total], rel_tol=1e-6):
            issues.append("期末总资产与资产总额不一致，请核对期间")
    def comparable(*fields):
        return all(data.get(field) is not None and field not in invalid + missing and isinstance(data[field], Real) and not isinstance(data[field], bool) for field in fields)
    for direct, ending in (("accounts_receivable", "ending_accounts_receivable"), ("inventory", "ending_inventory"), ("accounts_payable", "ending_accounts_payable"), ("prepayments", "ending_prepayments"), ("advance_receipts", "ending_advance_receipts")):
        if comparable(direct, ending) and not math.isclose(data[direct], data[ending], rel_tol=1e-6, abs_tol=1):
            issues.append(f"{LABELS[direct]}与{LABELS[ending]}不一致，请统一期末余额口径")
    for target, a, b, subtract in (("gross_profit", "revenue", "cost_of_goods_sold", True), ("ending_equity", "total_assets", "total_liabilities", True), ("scheduled_debt_service", "annual_principal_repayment", "annual_interest_payment", False)):
        if comparable(target, a, b):
            expected = data[a]-data[b] if subtract else data[a]+data[b]
            if not math.isclose(data[target], expected, rel_tol=1e-6, abs_tol=1):
                issues.append(f"{LABELS[target]}与{LABELS[a]}{'减' if subtract else '加'}{LABELS[b]}不一致，请核对主体、期间及调整明细")
    for components, upper in ((("short_term_debt", "long_term_debt", "current_portion_long_term_debt"), "total_liabilities"), (("short_term_debt", "current_portion_long_term_debt"), "current_liabilities")):
        known = [key for key in components if comparable(key)]
        if known and comparable(upper) and sum(data[key] for key in known) > data[upper] + 1:
            issues.append("已知" + "、".join(LABELS[key] for key in known) + "小计大于" + LABELS[upper] + "，请核对重复列报或债务归属")
    known_service = [key for key in ("annual_principal_repayment", "annual_interest_payment") if comparable(key)]
    if len(known_service) == 1 and comparable("scheduled_debt_service") and data["scheduled_debt_service"] + 1 < sum(data[key] for key in known_service):
        issues.append("现有年度偿债本息小于已知还本或付息金额；缺少另一分项不能把已知债务支出略去")
    if comparable("cash_and_equivalents", "restricted_cash", "minimum_cash_reserve", "available_internal_funds"):
        extra = data.get("confirmed_additional_internal_funds")
        if extra is None or extra == "" or comparable("confirmed_additional_internal_funds"):
            cash_limit = max(0, data["cash_and_equivalents"]-data["restricted_cash"]-data["minimum_cash_reserve"]) + (extra or 0)
            if data["available_internal_funds"] > cash_limit + 1:
                issues.append("可用自有资金超过扣受限款和最低经营留存后的现金余量及已落实额外自有资金，请核对时间基准与独立资金来源")
    period = str(data.get("report_period") or "未提供")
    period_known = period not in {"未提供", "未注明", "nan", "None", ""}
    return {"missing": missing, "invalid": invalid, "issues": issues,
            "coverage": round((len(DATA_FIELDS) - len(missing) - len(invalid)) / len(DATA_FIELDS) * 100),
            "core_missing": [x for x in CORE_FIELDS if x in missing], "period_known": period_known,
            "blocked": bool(invalid or issues), "note": "字段覆盖率衡量信息完整性，不表示企业信用或获批概率。"}


def simulate_repayment(data: Mapping[str, Any], profile: Mapping[str, Any], *, cash_drop: float = 0.2, rate_up: float = 0.01) -> dict[str, Any]:
    """Next twelve months of annuity payments plus existing debt; no CFADS imputation."""
    rate, months = float(profile["assumed_rate"]), int(profile["months"])
    if not 0 <= rate <= 1 or not 1 <= months <= 120 or not 0 <= cash_drop <= 1 or not 0 <= rate_up <= 1:
        raise ValueError("压力测试参数超出范围")
    gap = max(0.0, float(profile["amount"]) - float(profile["internal_funds"]))
    def annual_payment(r: float) -> float:
        return gap * annual_annuity_factor(r, months) * min(months, 12) / 12
    period = str(data.get("report_period") or "")
    annual = bool(re.fullmatch(r"20\d{2}(?:年度|年|-12-31)?", period.strip()))
    cfads, existing = data.get("cash_flow_available_for_debt_service"), data.get("scheduled_debt_service")
    available = annual and all(isinstance(v, Real) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1e15 for v in (cfads, existing)) and existing >= 0
    scenarios = []
    for name, drop, up in (("基准情景", 0.0, 0.0), ("现金流承压", cash_drop, 0.0), ("利率上行", 0.0, rate_up), ("双重压力", cash_drop, rate_up)):
        new_service = annual_payment(rate + up)
        total = new_service + existing if available else None
        cash = (cfads * (1 - drop) if cfads >= 0 else cfads * (1 + drop)) if available else None
        dscr = cash / total if total and cash is not None else None
        scenarios.append({"scenario": name, "assumed_rate": rate + up, "cash_drop": drop, "new_annual_service": new_service,
                          "total_annual_service": total, "cfads": cash, "dscr": dscr})
    return {"gap": gap, "scenarios": scenarios, "available": available,
            "note": "统一等额本息下，月供×min(期限月数,12)加现有未来12个月偿债本息；不假设到期续贷。利率为用户情景假设，非市场报价；CFADS降幅不是收入预测。年度输入不能验证月内现金安全。",
            "missing_reason": None if available else "需提供年度报告期、年度CFADS及现有年度偿债本息，才可评估整体偿付覆盖率。"}


def match_routes(data: Mapping[str, Any], profile: Mapping[str, Any], quality: Mapping[str, Any], risk: Mapping[str, Any]) -> list[dict[str, Any]]:
    equipment = profile["purpose"] == "设备购置"
    has_equipment = equipment or (profile["purpose"] == "综合融资" and (data.get("equipment_funding_need") or 0) > 0)
    receivables = "可提供" if isinstance(data.get("eligible_receivables"), Real) and data["eligible_receivables"] > 0 else "无" if data.get("eligible_receivables") == 0 else profile.get("receivables", "未确认")
    collateral = "可提供" if isinstance(data.get("unencumbered_collateral_value"), Real) and data["unencumbered_collateral_value"] > 0 else "无" if data.get("unencumbered_collateral_value") == 0 else profile.get("collateral", "未确认")
    high = [d["label"] for d in risk["dimensions"].values() if d["risk_level"] == "较高"]
    routes = [
        {"id": "working", "name": "经营周转贷款", "subtitle": "以经营现金流作为还款基础", "source": "KB-001", "priority": 1 if not equipment else 4,
         "status": "用途不符" if equipment else "适合进一步核验", "evidence": [f"本次资金用途：{profile['purpose']}", "需评估真实周转需求与还款来源"],
         "conditions": ["核验纳税、征信及账户流水", "核验贷款用途与购销合同"], "materials": ["购销合同与资金用途说明", "近12个月银行流水", "纳税申报与完税记录"]},
        {"id": "receivable", "name": "应收账款融资", "subtitle": "以可核验的交易与应收债权为基础", "source": "KB-002", "priority": 2,
         "status": "适合进一步核验" if receivables == "可提供" else "条件待补" if receivables != "无" else "暂不适配",
         "evidence": [f"可融资应收债权：{receivables}（已填金额优先）", "账面应收余额不等于可融资债权"],
         "conditions": ["核验债权真实性、账龄和回款安排", "核验转让限制、质押或重复融资情况"], "materials": ["应收账款账龄明细", "合同、发票及验收凭证", "债务人确权与回款计划"]},
        {"id": "secured", "name": "抵质押融资", "subtitle": "结合资产权属与可接受的担保物", "source": "KB-003", "priority": 3,
         "status": "适合进一步核验" if collateral == "可提供" else "暂不适配" if collateral == "无" else "条件待补",
         "evidence": [f"可用担保资产：{collateral}（已填金额优先）", "资产账面价值不等于可获批额度"],
         "conditions": ["核验资产权属、登记及既有负担", "由专业机构评估担保物价值"], "materials": ["资产权属与清单", "已有抵质押登记信息", "担保物评估资料"]},
        {"id": "leasing", "name": "设备融资租赁", "subtitle": "围绕真实设备采购与租赁现金流", "source": "KB-004", "priority": 1 if equipment else 4,
         "status": "适合进一步核验" if has_equipment else "暂不适配", "evidence": [f"本次资金用途：{profile['purpose']}", "需核验租赁物真实性及权属"],
         "conditions": ["取得设备报价与采购合同，核验租赁物适格性、权属与价值", "匹配收入现金流与租金，核验剩余使用年限和总成本"], "materials": ["设备采购合同与报价", "租赁物权属及剩余使用年限资料", "设备投资与现金流预算"]},
    ]
    for route in routes:
        if route["status"] == "适合进一步核验":
            if quality["blocked"] or quality["core_missing"] or not quality["period_known"]:
                route["status"] = "先补数据"
            elif high:
                route["status"] = "先处理风险"
        route["risk_flags"] = high
    return sorted(routes, key=lambda x: x["priority"])


TOOLS = {
    "inspect_data": ("核验企业数据", (), "检查字段、金额口径与报告期间；返回阻断问题与缺失项。"),
    "calculate_ratios": ("深度分析财务指标", ("inspect_data",), "计算盈利、偿债、现金流和营运周转指标，保留公式、来源及资金占用敏感性。"),
    "assess_risk": ("识别融资风险", ("calculate_ratios",), "按透明的演示筛查规则评估五个风险维度。"),
    "retrieve_knowledge": ("检索融资知识", (), "按任务与资金用途检索有来源的本地融资知识条目。"),
    "simulate_repayment": ("执行压力测试", ("calculate_ratios",), "按用户假设计算新增还款和现金流、利率压力情景。"),
    "match_routes": ("筛选融资路径", ("assess_risk", "retrieve_knowledge", "simulate_repayment"), "结合风险、用途、债权和担保条件比较四类融资路径。"),
    "optimize_financing_portfolio": ("计算融资组合", ("inspect_data", "assess_risk", "simulate_repayment", "match_routes"), "求解信用、应收、抵质押和设备租赁的组合金额，先最大覆盖缺口再最小化假设成本，受渠道容量、用途和压力偿债约束。"),
    "analyze_industry_region": ("分析行业与地区融资环境", ("optimize_financing_portfolio",), "结合填报行业、地区、财务指标与融资组合，检索公开资料并调用大模型分析行业资金特点、区域环境、同行融资机制及企业适配；核验原站正文、90天时效与适用范围，提取风险原句并通过知识库规则触发市场压力情景，重新求解融资组合；保留基础组合对照。"),
    "prepare_deliverables": ("生成融资分析报告", ("assess_risk", "match_routes", "simulate_repayment", "optimize_financing_portfolio", "analyze_industry_region"), "输出量化融资组合、行业地区分析、风险、压力测试和具体改善建议。"),
}


class DiligenceRun:
    def __new__(cls,data,profile,goal,source):
        if cls is DiligenceRun and data.get("statement_schema") == "public-v2":
            if profile.get("decision_engine") == "enterprise-v3":
                from finbridge.enterprise_run import EnterpriseDecisionRun
                return object.__new__(EnterpriseDecisionRun)
            from finbridge.public_run import PublicDecisionRun
            return object.__new__(PublicDecisionRun)
        return object.__new__(cls)
    def __init__(self, data: Mapping[str, Any], profile: Mapping[str, Any], goal: str, source: str):
        goal = {"融资准备": "融资组合", "风险排查": "风险分析"}.get(goal, goal)
        if goal not in GOALS:
            raise ValueError("不支持的任务类型")
        self.data, derivations = enriched_financial_data(clean_data(data))
        self.profile = clean_data(profile)
        self.industry_analyzer = None
        self.context_unavailable_reason = None
        for field in ("amount", "internal_funds", "months", "assumed_rate"):
            v = self.profile.get(field)
            if isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) or not 0 <= v <= 1e15:
                raise ValueError(f"任务参数无效：{field}")
        if not 1 <= self.profile["months"] <= 120 or int(self.profile["months"]) != self.profile["months"] or self.profile["assumed_rate"] > 1:
            raise ValueError("融资期限或假设利率超出范围")
        if self.profile.get("purpose") not in ({"经营周转", "订单备货", "设备购置", "综合融资"} | ({"研发周转"} if data.get("statement_schema")=="public-v2" else set())):
            raise ValueError("请选择受支持的资金用途")
        self.data.update(financing_need=self.profile["amount"], available_internal_funds=self.profile["internal_funds"])
        self.result = {"id": "FB-" + uuid.uuid4().hex[:8].upper(), "goal": goal,
                       "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                       "fingerprint": fingerprint(data, profile), "source": source, "data": self.data,
                       "profile": self.profile, "derivations": derivations, "outputs": {}, "events": [], "mode": "本地工作流", "status": "执行中"}

    def execute(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        tools = getattr(self,"tools",TOOLS)
        start = perf_counter()
        event = {"step": len(self.result["events"]) + 1, "tool": name, "arguments": dict(arguments or {})}
        try:
            if name not in tools:
                raise ValueError("未授权的工具")
            if arguments:
                raise ValueError("此工具不接受参数；只能使用已锁定的企业数据与任务需求")
            if name in self.result["outputs"]:
                output = self.result["outputs"][name]
                event["cached"] = True
            else:
                missing = [dep for dep in tools[name][1] if dep not in self.result["outputs"]]
                if missing:
                    raise ValueError("请先执行依赖工具：" + ", ".join(missing))
                output = self._dispatch(name)
                self.result["outputs"][name] = output
            event.update(status="完成", label=tools[name][0], result=deepcopy(output))
        except (ValueError, TypeError, KeyError) as exc:
            output = {"error": str(exc)}
            event.update(status="失败", label=tools.get(name, (name,))[0], result=output)
        event["duration_ms"] = round((perf_counter() - start) * 1000, 2)
        self.result["events"].append(event)
        return output

    def _dispatch(self, name: str) -> Any:
        out = self.result["outputs"]
        if name == "inspect_data":
            return check_data(self.data)
        if name == "calculate_ratios":
            valid = {k: v for k, v in self.data.items() if k not in out["inspect_data"]["invalid"]}
            ratios = calculate_deep_metrics(valid)
            for key, value in ratios.items():
                value["label"] = LABELS.get(key, key)
            return ratios
        if name == "assess_risk":
            return analyze_financial_risk({k: v for k, v in self.data.items() if k not in out["inspect_data"]["invalid"]})
        if name == "retrieve_knowledge":
            query = f"{self.result['goal']} {self.profile['purpose']} 应收账款 担保"
            hits = sorted(KNOWLEDGE, key=lambda doc: -sum(tag in query for tag in doc["tags"]))
            return {"query": query, "method": "本地条目关键词检索", "documents": deepcopy(hits), "verified_on": "2026-10-11", "note": "知识摘要用于解释融资方式；路径排序与风险阈值是本项目的演示方法，不是监管规则。"}
        if name == "match_routes":
            routes = match_routes(self.data, self.profile, out["inspect_data"], out["assess_risk"])
            stressed = any(s["dscr"] is not None and s["dscr"] < 1 for s in out["simulate_repayment"]["scenarios"])
            for route in routes:
                if route["status"] == "适合进一步核验" and (not out["simulate_repayment"]["available"] or stressed):
                    route["status"] = "先复核偿付能力"
                if self.profile["amount"] <= self.profile["internal_funds"] and route["status"] not in {"用途不符", "暂不适配"}:
                    route["status"] = "暂不需新增融资"
            return routes
        if name == "simulate_repayment":
            if out["inspect_data"]["blocked"]:
                return {"available": False, "gap": max(0, self.profile["amount"] - self.profile["internal_funds"]), "scenarios": [], "note": "数据核验存在阻断问题，暂停压力测试。", "missing_reason": "先修正无效字段或数据矛盾"}
            return simulate_repayment(self.data, self.profile)
        if name == "prepare_deliverables":
            return self._deliver()
        if name == "analyze_industry_region":
            if self.industry_analyzer is not None:
                return self.industry_analyzer(self.data, self.profile, out)
            return context_placeholder(self.data, self.profile, message=self.context_unavailable_reason)
        if name == "optimize_financing_portfolio":
            portfolio = build_financing_portfolio(self.data, self.profile, out["inspect_data"], out["assess_risk"])
            for bridge in self.result.get("derivations", []):
                if bridge["proxy"]:
                    warning = "偿债现金流采用代理口径：" + bridge["formula"]
                    portfolio["risk_flags"].insert(0, warning)
                    portfolio["algorithm"]["assumptions"].append(warning)
            from finbridge.task_focus import build_task_focus
            portfolio["task_focus"] = build_task_focus(self.data, self.profile, out, self.result["goal"], portfolio)
            return portfolio
        raise ValueError("工具不存在")

    def _deliver(self) -> dict[str, Any]:
        out, tasks = self.result["outputs"], []
        quality = out["inspect_data"]
        def add(title: str, owner: str, priority: str, evidence: str):
            tasks.append({"id": f"ACT-{len(tasks)+1:03}", "title": title, "owner": owner, "priority": priority, "evidence": evidence, "completed": False})
        if quality["invalid"]:
            add("修正无效财务字段：" + "、".join(LABELS.get(x, x) for x in quality["invalid"]), "财务负责人", "优先", "数据核验")
        for issue in quality["issues"]:
            add(issue, "财务负责人", "优先", "数据核验")
        if not quality["period_known"]:
            add("确认报告期及年报/中期口径", "财务负责人", "优先", "报告期间缺失")
        if quality["core_missing"]:
            add("补齐基础报表：" + "、".join(LABELS[x] for x in quality["core_missing"]), "财务负责人", "优先", "核心字段缺失")
        for field in ("operating_cash_flow", "cash_flow_available_for_debt_service", "scheduled_debt_service"):
            if field in quality["missing"]:
                add("补充" + LABELS[field], "财务负责人", "优先", "现金流及偿付测算输入缺失")
        for dimension in out["assess_risk"]["dimensions"].values():
            if dimension["risk_level"] in {"较高", "关注"}:
                add("复核" + dimension["label"] + "并形成改善说明", "财务负责人", "优先" if dimension["risk_level"] == "较高" else "常规", "；".join(e.get("rule_label", e["rule"]) for e in dimension["evidence"] if e["triggered"]))
        add("核对报告期、现金流口径和存量未来12个月还本付息计划", "企业财务负责人", "优先", "分析输入复核")
        high = [d["label"] for d in out["assess_risk"]["dimensions"].values() if d["risk_level"] == "较高"]
        status = "数据待修正" if quality["blocked"] else "待补充关键资料" if quality["core_missing"] or not quality["period_known"] or not out["simulate_repayment"]["available"] else "风险需复核" if high else "可继续组合测算"
        stressed = any(s["dscr"] is not None and s["dscr"] < 1 for s in out["simulate_repayment"]["scenarios"])
        if stressed:
            add("调整融资金额、期限或还款安排，复核压力情景覆盖不足", "企业负责人", "优先", "新增及现有债务合计DSCR低于1")
            findings_note = "原始全额融资请求的压力测试出现现金流不足以覆盖未来12个月本息的情景；拟议方案另按削减后的债务金额测算，不能混用两者。"
            if status == "可继续组合测算":
                status = "偿付压力需复核"
        else:
            findings_note = None
        findings = [f"外部资金缺口为 {fmt(max(0, self.profile['amount'] - self.profile['internal_funds']), '元')}，由需求总额减可用自有资金计算。",
                    f"已形成 {sum(x['value'] is not None for x in out['calculate_ratios'].values())} 项可计算指标；字段覆盖率 {quality['coverage']}%。"]
        findings.append("需优先复核：" + "、".join(high) if high else "当前数据未触发较高风险规则；仍需核验征信、交易真实性及还款来源。")
        if findings_note:
            findings.append(findings_note)
        if not out["simulate_repayment"]["available"]:
            findings.append(out["simulate_repayment"]["missing_reason"])
        if self.profile["internal_funds"] >= self.profile["amount"]:
            findings.append("按填报金额，自有资金可覆盖需求，暂无新增融资缺口；仍需确认自有资金的可支配性。")
            if status == "可继续组合测算":
                status = "暂无新增融资缺口"
        portfolio = effective_portfolio(out)
        market = out.get("analyze_industry_region", {}).get("market_decision")
        if market:
            findings.append("近期市场研究：" + market["status"] + "；分析基准日" + market["as_of"] + "。")
            if market["changed"]:
                add(market["action"], "企业财务负责人", "优先", "近期证据触发市场压力重算；" + market["version"])
        funding = portfolio["funding"]
        findings.insert(0, f"融资组合：自有资金 {fmt(funding['internal_used'], '元')}，新增债务 {fmt(funding['debt_total'], '元')}，尚未落实缺口 {fmt(funding['unfunded_gap'], '元')}。")
        for suggestion in portfolio["recommendations"]:
            add(suggestion["action"], "企业财务负责人", "优先", suggestion["title"] + "；" + str(suggestion["quantification"]))
        from finbridge.result_review import build_result_review
        from finbridge.task_focus import build_task_focus, focus_markdown
        focus = build_task_focus(self.data, self.profile, out, self.result["goal"])
        findings.insert(0, focus["summary"])
        if self.result["goal"] == "风险分析":
            threshold = focus.get("risk", {}).get("threshold")
            if threshold and threshold["cash_improvement"] > .01:
                add("补足可靠的年度还款现金，或协商减少当年本息", "企业财务负责人", "优先", "至少改善年度还款现金" + fmt(threshold["cash_improvement"], "元") + "；两种改善路径不可重复计入")
        return {"task_focus": focus, "decision_review": build_result_review(self.result), "readiness": status, "findings": findings, "tasks": tasks, "drivers": financial_drivers(self.data, out["calculate_ratios"]),
                "limitations": ["模拟或用户提供的数据未经审计；演示阈值不构成银行评分、违约预测或授信意见。", "不接入银行产品库、实时利率、征信、工商或税务接口；路径是融资方式的准备建议。", "压力测试采用用户假设，不预测真实现金流；实际资金成本和审批以机构核验为准。"]}

    def local(self, progress: Callable | None = None) -> dict[str, Any]:
        order = list(TOOLS)
        if self.result["goal"] == "方案比较":
            order = ["inspect_data", "retrieve_knowledge", "calculate_ratios", "simulate_repayment", "assess_risk", "match_routes", "optimize_financing_portfolio", "analyze_industry_region", "prepare_deliverables"]
        elif self.result["goal"] == "风险分析":
            order = ["inspect_data", "calculate_ratios", "assess_risk", "simulate_repayment", "retrieve_knowledge", "match_routes", "optimize_financing_portfolio", "analyze_industry_region", "prepare_deliverables"]
        for name in order:
            if name in self.result["outputs"]:
                continue
            self.execute(name)
            if progress:
                progress(self.result["events"][-1])
        return self.finish()

    def finish(self) -> dict[str, Any]:
        self.result["status"] = "已完成" if "prepare_deliverables" in self.result["outputs"] else "未完成"
        return deepcopy(self.result)


def financing_plan_markdown(plan: Mapping[str, Any] | None) -> list[str]:
    if not plan:
        return ["## 融资决策方案", "此任务为旧版快照，尚未执行融资决策工具。请重新启动任务生成完整方案。"]
    funding, repayment = plan["funding"], plan["repayment"]
    primary, industry = plan["primary"], plan["industry"]
    lines = ["## 融资决策方案", f"### 决策结论 · {plan['decision']['title']}", plan["decision"]["summary"]]
    lines.extend("- " + x for x in plan["decision"]["reasons"])
    lines.extend(["### 资金结构与尚未落实的缺口",
        f"总需求：{fmt(funding['need'], '元')}；本次使用自有资金：{fmt(funding['internal_used'], '元')}；外部缺口：{fmt(funding['gap'], '元')}。",
        f"现金流测算的债务预算上限：{fmt(funding['debt_capacity'], '元')}；主方案拟议新增债务：{fmt(funding['proposed_debt'], '元')}；尚未落实缺口：{fmt(funding['unallocated_gap'], '元')}。",
        "尚未落实缺口需要另行确认股东注资、加速回款或缩减/分期采购的可行性，不能计作已筹资金。主方案与备选方案互为替代，不能重复加总。",
        f"### 主方案 · {primary['title']}", f"状态：{primary['status']}；拟议金额：{fmt(primary['amount'], '元')}。", primary["reason"],
        "还款匹配：" + primary["repayment_match"], "启动条件：" + "；".join(primary["conditions"]), "需准备：" + "；".join(primary["materials"]),
        "### 备选方案与切换条件"])
    for alternate in plan["alternatives"]:
        lines.extend([f"- {alternate['title']} · {alternate['status']} · 金额 {fmt(alternate.get('amount'), '元')}",
            "  适用理由：" + alternate["reason"], "  切换前核验：" + "；".join(alternate["conditions"]),
            "  未作为首选：" + alternate.get("why_not_primary", "需进一步核验")])
    lines.extend(["### 期限、成本与偿付约束",
        f"测算期限：{repayment['months']}个月；假设年利率：{repayment['assumed_rate']:.1%}；压力年利率：{repayment['stress_rate']:.1%}。",
        "本项目方案预算假设：CFADS下降20%、利率上行1个百分点、压力DSCR目标1.20。以上为演示安全余量，非监管统一门槛或银行审批标准。",
        "预算公式：" + repayment["capacity_formula"],
        f"拟议债务月供：{fmt(repayment['monthly_payment'], '元')}；假设总利息：{fmt(repayment['total_interest'], '元')}；假设本息总额：{fmt(repayment['total_principal_interest'], '元')}。",
        "以上为等额本息预算口径，未计担保、评估、服务费等；保理和租赁实际收付款结构须以机构报价重算，不据此声称真实总成本。"])
    for key, label in (("base", "基准"), ("stress", "双重压力")):
        scenario = repayment.get(key) or {}
        lines.append(f"- {label}：CFADS {fmt(scenario.get('cfads'), '元')}；现有年偿债 {fmt(scenario.get('existing_annual_service'), '元')}；新增未来12个月本息 {fmt(scenario.get('new_annual_service'), '元')}；整体DSCR {fmt(scenario.get('dscr'), '倍')}。")
    for term in plan.get("term_comparison", []):
        lines.append(f"- {term['months']}个月比较：债务预算上限 {fmt(term.get('debt_capacity'), '元')}；拟议债务 {fmt(term.get('proposed_debt'), '元')}；剩余缺口 {fmt(term.get('remaining_gap'), '元')}；压力DSCR {fmt(term.get('stress_dscr'), '倍')}；{term['status']}。")
    lines.extend(["### 行业痛点与方案适配", f"识别场景：{industry['name']}；仅按填报行业匹配经营情景，仍需企业核实。"])
    lines.extend("- 痛点：" + x for x in industry["pain_points"])
    lines.extend("- 工具与用途：" + x for x in industry["financing_tools"])
    lines.extend(["还款匹配：" + industry["repayment_match"], "专项核验材料：" + "；".join(industry["verification_materials"]), "### 决策门槛与依据"])
    for gate in plan["gates"]:
        lines.append(f"- {gate['label']} · {gate['status']}：{gate['detail']}；依据：{gate['evidence']}")
    lines.append("### 实施安排与进入下一阶段的条件")
    for phase in plan["schedule"]:
        lines.extend([f"- {phase['phase']} / 责任人：{phase['owner']}", "  事项：" + "；".join(phase["actions"]), "  进入下一阶段条件：" + phase["exit_condition"]])
    lines.append("### 受阻与退出预案")
    lines.extend(f"- {trigger['trigger']} → {trigger['action']}" for trigger in plan["exit_triggers"])
    lines.extend("- " + limit for limit in plan["limitations"])
    return lines


def portfolio_markdown(plan: Mapping[str, Any] | None) -> list[str]:
    if not plan:
        return ["## 融资组合", "此历史结果尚未计算融资组合，请重新生成分析。"]
    f, algorithm = plan["funding"], plan["algorithm"]
    lines = ["## 定量融资组合", f"组合状态：{plan['status']}；风险状态：{plan['risk_status']}",
        f"资金需求 {fmt(f['need'], '元')}；投入自有资金 {fmt(f['internal_used'], '元')}；外部缺口 {fmt(f['gap'], '元')}；新增债务本金 {fmt(f['debt_total'], '元')}；尚未覆盖用途缺口 {fmt(f['unfunded_gap'], '元')}。", f["note"]]
    if plan["available"]:
        table = ["| 渠道 | 建议本金 | 占新增融资 | 容量上限 | 假设年利率 | 期限 | 总利息 | 一次性费 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for c in plan["composition"]:
            table.append(f"| {c['name']} | {fmt(c['amount'], '元')} | {fmt(c['share'], '%')} | {fmt(c['capacity'], '元')} | {fmt(c['rate'], '%')} | {c['months']}个月 | {fmt(c['total_interest'], '元')} | {fmt(c['total_fee'], '元')} |")
        lines.append("\n".join(table))
        lines.extend([f"全期限假设总利息：{fmt(f['total_assumed_interest'], '元')}；一次性费用：{fmt(f['fees_due'], '元')}；含费用总现金需求：{fmt(f['total_cash_need'], '元')}；费用另筹缺口：{fmt(f['fee_funding_gap'], '元')}；含费用总待落实缺口：{fmt(f['total_unfunded_cash'], '元')}。", "### 为什么这样分配"])
        for c in plan["composition"]:
            lines.extend([f"- {c['name']} / {fmt(c['amount'], '元')}：{c['reason']}", *["  测算条件：" + assumption for assumption in c["assumed"]]])
        lines.append("### 融资组合压力测试")
        from finbridge.terminology import REPAYMENT_HELP, STRESS_HELP, CASH_GAP_HELP
        lines.extend([REPAYMENT_HELP, STRESS_HELP, CASH_GAP_HELP])
        table = ["| 情景 | 年度还款现金（CFADS） | 新增未来12个月本息 | 存量未来12个月本息 | 还款覆盖倍数（DSCR） | 达到目标还需年度现金 |", "| --- | --- | --- | --- | --- | --- |"]
        for scenario in plan["scenarios"]:
            table.append(f"| {scenario['label']} | {fmt(scenario['cfads'], '元')} | {fmt(scenario['new_annual_service'], '元')} | {fmt(scenario['existing_annual_service'], '元')} | {fmt(scenario['dscr'], '倍')} | {fmt(scenario['gap_to_target'], '元')} |")
        lines.extend(["\n".join(table), plan["repayment_note"]])
        if plan.get("alternatives"):
            lines.append("### 与单一渠道比较")
            table = ["| 方案 | 债务本金 | 未覆盖用途缺口 | 假设总利息及费用 | 双重压力DSCR |", "| --- | --- | --- | --- | --- |"]
            for alternative in plan["alternatives"]:
                table.append(f"| {alternative['title']} | {fmt(alternative['debt_total'], '元')} | {fmt(alternative['unfunded_gap'], '元')} | {fmt(alternative['total_cost'], '元')} | {fmt(alternative['stress_dscr'], '倍')} |")
            lines.extend(["\n".join(table), "同一需求和压力预算下的替代方案，金额不得与组合叠加；各方案覆盖额、期限不同，总利息及费用不能直接当作同金额年化成本排名。"])
        allocation = plan["purpose_allocation"]
        lines.extend(["### 资金用途分配", "| 用途 | 预算 | 分配自有资金 | 分配债务本金 | 未覆盖缺口 |\n| --- | --- | --- | --- | --- |\n" + "\n".join(f"| {label} | {fmt(allocation[budget], '元')} | {fmt(allocation[internal], '元')} | {fmt(allocation[debt], '元')} | {fmt(allocation[gap], '元')} |" for label, budget, internal, debt, gap in (("经营周转", "working_capital_funding_need", "working_internal", "working_debt", "working_unfunded"), ("设备购置", "equipment_funding_need", "equipment_internal", "equipment_debt", "equipment_unfunded"))), allocation["note"]])
    lines.append("### 风险与实质性建议")
    lines.extend("- " + flag for flag in plan["risk_flags"])
    for suggestion in plan["recommendations"]:
        lines.extend([f"#### {suggestion['title']}", "定量依据：" + suggestion["quantification"], "原因：" + suggestion["reason"], "建议：" + suggestion["action"]])
    lines.extend(["### 组合求解方法", algorithm["name"], *["- " + goal for goal in algorithm["objective"]], f"候选顶点检查数：{algorithm['checked_candidates']}；本项目压力偿债目标DSCR：{algorithm['target_dscr']:.2f}（非监管统一标准）。"])
    lines.extend(f"- {c['label']}：上限 {fmt(c['limit'], '元')} {('/12个月' if c['unit'] == '元/年' else '')}；组合使用 {fmt(c.get('used'), '元')}；剩余空间 {fmt(c.get('remaining'), '元')}。" for c in algorithm["constraints"])
    lines.extend("- " + assumption for assumption in algorithm["assumptions"])
    industry = plan["industry"]
    lines.extend(["### 行业经营要点 · " + industry["name"], *["- " + pain for pain in industry["pain_points"]], "还款周期匹配：" + industry["repayment_match"]])
    return lines


def report_markdown(run: Mapping[str, Any]) -> str:
    if run.get("public_analysis") is not None:
        from finbridge.public_report import public_report_markdown
        return public_report_markdown(run)
    out, profile, data = run["outputs"], run["profile"], run["data"]
    delivery = out["prepare_deliverables"]
    lines = [f"# 融智 · 企业财务分析与融资组合报告", f"分析编号：{run['id']}  |  生成时间：{run['created_at']}",
             f"企业：{data.get('company_name', '未命名企业')}  |  报告期：{data.get('report_period', '未提供')}",
             f"数据来源：{run['source']}  |  执行模式：{run['mode']}  |  任务：{run['goal']}",
             "## 任务与结论", f"资金需求：{fmt(profile['amount'], '元')}；自有资金：{fmt(profile['internal_funds'], '元')}；期限：{int(profile['months'])}个月；用途：{profile['purpose']}",
             f"原始请求偿付状态：{delivery['readiness']}", *[f"- {x}" for x in delivery["findings"]]]
    from finbridge.report_brief import build_report_brief, brief_markdown
    lines[4:4] = brief_markdown(build_report_brief(run)) + ["## 附录：完整计算、输入核对与证据"]
    from finbridge.terminology import terminology_markdown, REPAYMENT_HELP
    lines.insert(4, REPAYMENT_HELP)
    lines.extend(terminology_markdown())
    if out.get("analyze_industry_region", {}).get("market_decision", {}).get("changed"):
        lines.append("本报告主建议采用近期证据触发的市场压力组合；基础组合在后文对照，二者不可叠加。")
    from finbridge.result_review import build_result_review, review_markdown
    lines.extend(review_markdown(build_result_review(run)))
    lines.extend(portfolio_markdown(effective_portfolio(out)))
    lines.extend(context_markdown(out.get("analyze_industry_region"), out.get("calculate_ratios", {})))
    if delivery.get("drivers"):
        lines.append("## 经营改善资金敏感性")
        for driver in delivery["drivers"]:
            lines.extend([f"- {driver['title']}：{fmt(driver['value'], driver['unit'])}", driver["reason"], "建议：" + driver["action"]])
    if run.get("derivations"):
        lines.append("## 原始数据的计算桥接")
        lines.extend(f"- {bridge['formula']} → {fmt(bridge['value'], '元')}" for bridge in run["derivations"])
    lines.append("## 财务证据")
    for metric in out["calculate_ratios"].values():
        lines.extend([f"- {metric['label']}：{fmt(metric['value'], metric['unit'])}", f"  公式：{metric['formula']}；来源字段：{'、'.join(LABELS.get(x, x) for x in metric['sources'])}；期间：{metric['period']}"])
        if metric["data_issue"]:
            lines.append("  未计算原因：" + metric["data_issue"])
    lines.append("## 风险筛查")
    for dimension in out["assess_risk"]["dimensions"].values():
        lines.append(f"- {dimension['label']}：{dimension['risk_level']}（{dimension['data_sufficiency']}）")
        for evidence in dimension["evidence"]:
            lines.append(f"  {evidence.get('rule_label', evidence['rule'])}；实际结果={fmt(evidence['value'], evidence['unit'])}；是否触发={'是' if evidence['triggered'] else '否'}")
    lines.append("## 融资路径比较")
    for route in out["match_routes"]:
        lines.extend([f"### {route['name']} · {route['status']}", "依据：" + "；".join(route["evidence"]) + f"（{route['source']}）", "待核验：" + "；".join(route["conditions"])])
    lines.extend(["## 原始融资请求的偿付压力测试", f"本节按原始外部缺口 {fmt(out['simulate_repayment']['gap'], '元')} 计算，区别于上方主方案削减后的拟议债务预算。", out["simulate_repayment"]["note"]])
    for scenario in out["simulate_repayment"]["scenarios"]:
        lines.append(f"- {scenario['scenario']}：假设年利率 {scenario['assumed_rate']:.1%}；CFADS下降 {scenario['cash_drop']:.0%}；新增未来12个月本息 {fmt(scenario['new_annual_service'], '元')}；含现有债务DSCR {fmt(scenario['dscr'], '倍')}")
    if not out["simulate_repayment"]["available"]:
        lines.append(out["simulate_repayment"]["missing_reason"])
    lines.append("## 资金改善与执行建议（生成时快照）")
    lines.extend(f"- [ ] {t['id']} {t['title']} / 责任人：{t['owner']} / 优先级：{t['priority']} / 依据：{t['evidence']}" for t in delivery["tasks"])
    lines.append("## 引用资料")
    lines.extend(f"- {k['id']} {k['title']} / {k['publisher']} / 发布日期 {k['date']} / {k['url']}" for k in out["retrieve_knowledge"]["documents"])
    lines.append("## 使用边界")
    lines.extend("- " + x for x in delivery["limitations"])
    return "\n\n".join(lines)


def report_html(run: Mapping[str, Any]) -> str:
    # Escape all source and model-controlled text; standalone, printable artifact.
    body = []
    for line in report_markdown(run).split("\n\n"):
        if line == "## 任务与结论":
            plan = effective_portfolio(run["outputs"])
            if plan and plan["available"]:
                f = plan["funding"]
                cards = "".join('<div class="figure-card"><span>' + label + '</span><strong>' + html.escape(fmt(f[key], "元")) + '</strong></div>' for label, key in (("资金需求", "need"), ("组合债务本金", "debt_total"), ("用途待筹缺口", "unfunded_gap"), ("一次性费用另筹", "fee_funding_gap")))
                parts = [("自有资金", f["internal_used"], "#087f73")] + [(c["name"], c["amount"], color) for c, color in zip(plan["composition"], ("#5b86a6", "#a083ac", "#d3a654", "#72b8a0"))] + [("待筹缺口", f["unfunded_gap"], "#c95a4f")]
                segments, legends = [], []
                for label, amount, color in parts:
                    if amount <= 0:
                        continue
                    title = html.escape(label + " · " + fmt(amount, "元"))
                    segments.append(f'<span style="width:{amount / f["need"] * 100 if f["need"] else 0:.4f}%;background:{color}" title="{title}"></span>')
                    legends.append(f'<span><i style="background:{color}"></i>{title}</span>')
                stress = []
                for scenario in plan["scenarios"]:
                    dscr = scenario["dscr"]
                    if dscr is None:
                        continue
                    color = "#087f73" if dscr >= 1.2 else "#d3a654" if dscr >= 1 else "#c95a4f"
                    stress.append('<div class="stress-row"><span>' + html.escape(scenario["label"]) + f'</span><div class="stress-track"><i style="width:{min(max(dscr, 0) / 2 * 100, 100):.2f}%;background:{color}"></i></div><strong>{dscr:.2f}</strong></div>')
                from finbridge.terminology import REPAYMENT_HELP, STRESS_HELP, CASH_GAP_HELP
                body.append('<section class="summary-figure" aria-label="融资组合与压力测试概览"><div class="figure-cards">' + cards + '</div><h3>本次资金从哪里来</h3><div class="funding-bar">' + "".join(segments) + '</div><div class="funding-legend">' + "".join(legends) + '</div><h3>同一融资组合的压力偿债覆盖率</h3>' + "".join(stress) + '<p class="figure-note">' + html.escape(REPAYMENT_HELP + ' 虚线为1.20倍安全线；绿色≥1.20，黄色在1.00至1.20之间，红色<1.00。' + CASH_GAP_HELP) + '</p></section>')
        level = len(line) - len(line.lstrip("#"))
        if line.startswith("| "):
            rows = line.splitlines()
            table_rows = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
            body.append('<div class="table-wrap"><table><thead><tr>' + "".join("<th>" + html.escape(cell) + "</th>" for cell in table_rows[0]) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + html.escape(cell) + "</td>" for cell in row) + "</tr>" for row in table_rows[2:]) + "</tbody></table></div>")
        elif level in (1, 2, 3, 4) and line[level:level+1] == " ":
            body.append(f"<h{level}>{html.escape(line[level+1:])}</h{level}>")
        else:
            body.append("<p>" + html.escape(line).replace("\n", "<br>") + "</p>")
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>融智 · 企业财务分析与融资组合</title><style>body{max-width:1100px;margin:48px auto;padding:0 24px;font:15px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#163b35}h1{border-bottom:3px solid #128574;padding-bottom:20px}h2{margin-top:32px;color:#087f73}p{white-space:normal;overflow-wrap:anywhere}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px;margin:18px 0}th{background:#edf3f0;text-align:left}th,td{padding:9px;border:1px solid #dce6e1}.summary-figure{padding:22px;border:1px solid #dce6e1;background:#f7faf8;border-radius:10px}.figure-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.figure-card span{display:block;color:#5b706b;font-size:12px}.figure-card strong{display:block;font-size:21px}.funding-bar{height:28px;display:flex;overflow:hidden;border-radius:5px}.funding-legend{display:flex;gap:8px 18px;flex-wrap:wrap;font-size:12px;margin:12px 0}.funding-legend i{display:inline-block;width:10px;height:10px;margin-right:5px}.stress-row{display:grid;grid-template-columns:225px 1fr 44px;gap:12px;align-items:center;margin:10px 0;font-size:13px}.stress-track{background:#e1eae5;height:18px;position:relative}.stress-track:after{content:"";position:absolute;left:60%;top:-3px;height:24px;border-left:2px dashed #934332}.stress-track i{display:block;height:100%}.figure-note{font-size:12px;color:#5b706b}@media(max-width:640px){.figure-cards{grid-template-columns:1fr 1fr}.stress-row{grid-template-columns:145px 1fr 36px;font-size:11px}body{padding:0 14px;margin:24px auto}}@media print{body{margin:0;max-width:none}h2,h3{break-after:avoid}p{orphans:3;widows:3}thead{display:table-header-group}tr,.summary-figure{break-inside:avoid}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}</style><body>' + "".join(body) + "</body></html>"


def delivery_zip(run: Mapping[str, Any], tasks: list[dict[str, Any]], reviewed: bool = False) -> bytes:
    import csv
    output, table = io.BytesIO(), io.StringIO()
    writer = csv.DictWriter(table, fieldnames=["id", "title", "owner", "priority", "evidence", "completed"])
    writer.writeheader()
    for task in tasks:
        # Spreadsheet formula injection prevention in exported text cells.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v) for k, v in task.items()})
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", report_markdown(run))
        archive.writestr("report.html", report_html(run))
        archive.writestr("evidence.json", json.dumps(run, ensure_ascii=False, indent=2, allow_nan=False))
        archive.writestr("action-checklist.csv", table.getvalue().encode("utf-8-sig"))
        archive.writestr("delivery-status.json", json.dumps({"task_id": run["id"], "reviewed_in_session": reviewed,
            "completed_actions": sum(t["completed"] for t in tasks), "total_actions": len(tasks), "note": "会话复核标记不是电子签名。报告为生成时快照，行动清单为导出时进度。"}, ensure_ascii=False, indent=2))
    return output.getvalue()
