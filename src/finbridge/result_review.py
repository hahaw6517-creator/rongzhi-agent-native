"""Explain the actual locked inputs and binding limits without changing the solver."""
import math
from numbers import Real
from finbridge.data import FIELD_CATALOG
from finbridge.market_rules import effective_portfolio


def money(value):
    if value is None or value == "":
        return "未填写"
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        return str(value)[:100] + "（无效数值）"
    return f"{value/1e8:,.6f}亿元"


def build_result_review(run):
    out, data, profile = run["outputs"], run["data"], run["profile"]
    plan = effective_portfolio(out) or {}
    f = plan.get("funding", {})
    rows, causes = [], []
    for c in plan.get("composition", []):
        key = c["capacity_input"]
        raw = profile.get(key) if profile.get(key) not in (None, "") else data.get(key)
        origin = "任务条件覆盖上传数据" if profile.get(key) not in (None, "") else "企业数据"
        label = FIELD_CATALOG[key]["label"]
        if not c["enabled"]:
            status, action = "本次用途不适用", "核对资金用途；不应为增加融资金额而改用途。"
        elif raw is None or raw == "":
            status, action = "缺少容量依据", f"核实并填写“{label}”；账面资产不能自动代替可融资额度。"
        elif raw == 0:
            status, action = "输入明确为零", f"核对“{label}”是否确实为零；仅在有真实依据时修正。"
        elif c["capacity"] == 0:
            status, action = "融资比例为零", "核对该渠道融资比例及容量依据。"
        elif not c.get("amount"):
            status, action = "有容量，未被选用", "查看偿债预算和其他渠道成本；容量不等于建议借款。"
        else:
            status, action = "已纳入组合", "核实独立未占用额度、实际报价与还款安排。"
        rows.append(dict(channel=c["name"], field=label, key=key, group=FIELD_CATALOG[key]["group"],
            raw=raw, source=origin, capacity=c["capacity"], amount=c.get("amount"), status=status, action=action))
    budget = plan.get("algorithm", {}).get("service_budget")
    debt, gap = f.get("debt_total"), f.get("gap")
    if not plan.get("available"):
        title = "输入尚未通过核验，暂不能给出融资金额"
        causes = [r["reason"] for r in plan.get("recommendations", []) if r["title"] == "先补齐输入，暂不配置肯定融资金额"] or ["核对下方数据问题与完整测算中的阻断原因。"]
    elif gap == 0:
        title = "已填自有资金覆盖用途预算，无需新增借款"
    else:
        if rows and all(r["capacity"] == 0 for r in rows):
            causes.append("四个渠道的可用容量均为0，求解器没有可分配的融资本金。请先核对下表的容量依据。")
        if budget is not None and budget <= .01:
            causes.append("压力情景下，现有债务已占满可承受本息预算，当前无法增加债务。")
        if debt == 0 and not causes:
            causes.append("现有渠道与资金用途、偿债预算无法同时满足，请查看完整测算的约束。")
        title = "本次新增融资本金为0：先核对原因" if debt == 0 else "组合仍有资金缺口，需要调整计划" if (f.get("unfunded_gap") or 0) > .01 else "用途本金已覆盖，仍需核实费用与合同"
        if debt and (f.get("unfunded_gap") or 0) > .01:
            causes.append(f"用途预算尚缺{money(f['unfunded_gap'])}；可考虑减少或延期同额支出、落实真实非借款资金，修改条件后重算。")
    return dict(title=title, causes=causes, channels=rows, service_budget=budget,
        cfads=data.get("cash_flow_available_for_debt_service"), existing_service=data.get("scheduled_debt_service"),
        stress_drop=plan.get("algorithm", {}).get("planning_stress", {}).get("cash_drop", .2),
        target_dscr=plan.get("algorithm", {}).get("target_dscr", 1.2),
        snapshot=run.get("id", ""), note="本页金额是本次输入下的测算预算，不是银行已批额度。修改数据后须重新生成，旧报告不会自动更新。")


def review_markdown(review):
    lines = ["## 先看结论与待核对事项", review["title"], *["- " + s for s in review["causes"]],
             "### 本次实际采用的渠道输入", "| 渠道 | 容量依据字段 | 实际输入 | 数据来源 | 可用容量 | 状态 |", "| --- | --- | --- | --- | --- | --- |"]
    for r in review["channels"]:
        lines.append(f"| {r['channel']} | {r['field']} | {money(r['raw'])} | {r['source']} | {money(r['capacity'])} | {r['status']} |")
    lines.extend([f"新增未来12个月本息预算：{money(review['service_budget'])}（并非贷款本金）。", review["note"]])
    merged = []
    for line in lines:
        if line.startswith("| ") and merged and merged[-1].startswith("| "):
            merged[-1] += "\n" + line
        else:
            merged.append(line)
    return merged
