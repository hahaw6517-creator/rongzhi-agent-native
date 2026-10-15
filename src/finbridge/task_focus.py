"""Different financial decisions for different task goals; prose never sets money."""
from finbridge.portfolio import build_financing_portfolio, _service_factor
from finbridge.market_rules import effective_portfolio
from finbridge.analysis import financial_drivers
from finbridge.result_review import money

GOAL_GUIDANCE = {
    "融资组合": "先回答钱怎么凑、每个渠道借多少、还差多少、为什么选它。",
    "风险分析": "先回答最需要担心什么、现金流还能下降多少、至少要改善多少；融资金额只作背景。",
    "方案比较": "对真实重新求解的方案逐项比较金额、成本、还款和缺口，讲清选择代价；不能只换标题。",
}


def _risk_review(data, outputs, plan):
    risk = outputs.get("assess_risk", {}).get("dimensions", {})
    order = {"较高": 0, "无法判断": 1, "关注": 2, "暂未触发演示规则": 3}
    names = {"liquidity": "手头的钱够不够周转", "leverage": "欠债是不是偏多", "profitability": "生意是否赚钱",
             "cash_flow": "赚的钱有没有真正收回来", "debt_service": "现金够不够还本付息"}
    ranked = []
    for key, dim in sorted(risk.items(), key=lambda item: order.get(item[1]["risk_level"], 4)):
        evidence = [e for e in dim.get("evidence", []) if e["triggered"]]
        ranked.append(dict(question=names.get(key, dim["label"]), level=dim["risk_level"],
            reason="；".join(e["rule_label"] for e in evidence) or ("关键数据不足，还不能判断。" if dim["risk_level"] == "无法判断" else "目前没有触发项目筛查线，仍需结合实际经营核对。")))
    double = next((s for s in plan.get("scenarios", []) if s["id"] == "double"), None)
    cfads = data.get("cash_flow_available_for_debt_service")
    threshold = None
    if plan.get("available") and double and cfads is not None:
        service = double["new_annual_service"] + double["existing_annual_service"]
        target = plan["algorithm"]["target_dscr"]
        drop = plan["algorithm"]["planning_stress"]["cash_drop"]
        minimum_cash = service * target
        critical = 1-minimum_cash/cfads if cfads > 0 and service > 0 else None
        threshold = dict(minimum_cash=minimum_cash, current_cfads=cfads,
            cash_drop_limit=critical, already_below=cfads < minimum_cash,
            cash_improvement=max(0., minimum_cash/(1-drop)-cfads),
            service_reduction=max(0., service-double["cfads"]/target),
            planned_drop=drop, target=target,
            note="临界点固定本组合和加息假设，只改变年度可用于还款的现金；不代表营收下降比例、违约概率或月内安全。现有债务按上传本息，不重估其浮动利率。")
        if cfads < minimum_cash:
            ranked.append(dict(question="现有借法还能不能扛住还款", level="较高", reason="固定加息假设后，当前年度还款现金已低于项目安全线；先改善现金或协商还款。"))
        elif critical is not None and critical <= drop+1e-6:
            ranked.append(dict(question="压力一来，还款余量够不够", level="关注", reason=f"还款现金下降约{max(0., critical):.1%}就触及项目安全线，已接近设定的{drop:.0%}压力；不要在原组合上直接叠加借款。"))
    if (plan.get("funding", {}).get("unfunded_gap") or 0) > .01:
        ranked.append(dict(question="这笔支出还有多少钱没着落", level="关注",
            reason="用途预算还差"+money(plan["funding"]["unfunded_gap"])+"，要先落实真实资金或缩减、延后支出。"))
    ranked.sort(key=lambda r: order.get(r["level"], 4))
    return dict(ranked=ranked, threshold=threshold,
        improvements=financial_drivers(data, outputs.get("calculate_ratios", {})),
        scope="风险排序按项目规则严重程度排列，不是银行评级。这里的还款现金指CFADS，不是净利润。")


def _comparison(data, profile, outputs, base):
    if not base.get("available"):
        return dict(options=[], duplicates=[], note="输入尚未通过核验，先修正数据，不能编造可行方案。")
    stress = base["algorithm"]["planning_stress"]
    cautious = {"cash_drop": min(.4, max(.3, stress["cash_drop"]+.1)),
                "rate_up": min(.05, max(.02, stress["rate_up"]))}
    common = dict(quality=outputs["inspect_data"], risk=outputs["assess_risk"])
    variants = [
        ("coverage", "优先补足资金", "先尽量补足用途缺口，同样借款金额下再压低假设总成本。", base),
        ("repayment", "优先减轻一年内还款", "仍先尽量补足缺口，同样借款金额下优先减少未来12个月还款，可能增加长期总利息。",
         build_financing_portfolio(data, profile, **common, planning_stress=stress, selection_objective="repayment")),
        ("buffer", "多留一点抗风险余量", f"按还款现金下降{cautious['cash_drop']:.0%}、利率上升{cautious['rate_up']*100:g}个百分点重算，可能需要缩减支出或增加自有资金。",
         build_financing_portfolio(data, profile, **common, planning_stress=cautious)),
    ]
    if base.get("sme_basis"):
        variants[1]=(variants[1][0],"优先减轻还款最重年份", "同等拟申请金额下，减少全期限最重12个月还款；到期还本产品不会只计利息，可能增加全期利息。",variants[1][3])
    options, duplicates, seen = [], [], set()
    for key, title, reason, p in variants:
        # Equal channel amounts and contractual terms are the same cashflow plan.
        signature = tuple((c["id"], round(c["amount"], 2), c["months"], c["rate"], c["fee_rate"]) for c in p["composition"])
        if signature in seen:
            duplicates.append(title + "：在当前额度和约束下，与已展示方案得到相同金额分配。")
            continue
        seen.add(signature)
        if p.get("sme_basis"):
            from finbridge.sme_decision import peak_service_factor
            service=sum(c["amount"]*peak_service_factor(c["rate"]+stress["rate_up"],c["months"],c["repayment"]) for c in p["composition"])
        else:
            service = sum(c["amount"]*_service_factor(c["rate"]+stress["rate_up"], c["months"]) for c in p["composition"])
        total_service = service+data["scheduled_debt_service"]
        cash = data["cash_flow_available_for_debt_service"]
        stressed_cash = cash*(1-stress["cash_drop"]) if cash >= 0 else cash*(1+stress["cash_drop"])
        passes = stressed_cash+1e-7 >= p["algorithm"]["target_dscr"]*total_service
        f=p["funding"]
        options.append(dict(id=key, title=title, reason=reason, debt=f["debt_total"], gap=f["unfunded_gap"],
            interest=f["total_assumed_interest"], fees=f["fees_due"], total_cost=f["total_assumed_interest"]+f["fees_due"],
            new_service=service, total_service=total_service, common_stress_dscr=stressed_cash/total_service if total_service > 0 else None,
            feasible=passes, status=("通过数学约束，但存在较高风险，先核对整改" if any(d.get("risk_level") == "较高" for d in outputs.get("assess_risk", {}).get("dimensions", {}).values()) else "通过本次数学约束，仍待机构核实") if passes else "现有债务尚未通过压力线，先处理存量还款",
            composition=[dict(name=c["name"], amount=c["amount"], months=c["months"], rate=c["rate"]) for c in p["composition"] if c["amount"] > 0],
            own_stress=p["algorithm"]["planning_stress"], constraints=p["algorithm"]["constraints"]))
    return dict(options=options, duplicates=duplicates, common_stress=stress,
        note="各方案互相替代，不能叠加。统一压力列采用相同现金降幅和加息假设；全期限总成本受借款金额、期限影响，不能直接当年化利率排名。金额相同的方案合并展示，不硬凑三套。")


def build_task_focus(data, profile, outputs, goal, plan=None):
    plan = plan if plan is not None else effective_portfolio(outputs) or {}
    f=plan.get("funding", {})
    result=dict(goal=goal, guidance=GOAL_GUIDANCE.get(goal, GOAL_GUIDANCE["融资组合"]), available=bool(plan.get("available")),sme_basis=bool(plan.get("sme_basis")))
    if not plan:
        return {**result, "title": "先完成基础计算", "summary": "当前数据还不足以形成这项分析。"}
    if goal == "风险分析":
        risk=_risk_review(data, outputs, plan)
        top=next((r for r in risk["ranked"] if r["level"] in {"较高", "无法判断", "关注"}), None)
        result.update(title="先看哪里最容易出问题", summary=("优先核对："+top["question"]+"。" if top else "目前没有触发项目风险线，仍要看还款压力和数据是否完整。"), risk=risk)
        if not plan.get("available"):
            result["summary"] = "数据还有待核对的地方，下面只作风险初筛；暂不能给出可靠的承债上限和现金下降临界点。"
    elif goal == "方案比较":
        comparison=_comparison(data, profile, outputs, plan)
        result.update(title="把几种借法放在一起比较", summary=f"本次得到{len(comparison['options'])}套不同的金额分配。先看缺口能补多少，再看一年内还款和总成本。", comparison=comparison)
    else:
        chosen=[c for c in plan.get("composition", []) if (c.get("amount") or 0) > 0]
        result.update(title="这笔钱准备怎么凑", summary=(f"自有资金用{money(f.get('internal_used'))}，新增借款计划{money(f.get('debt_total'))}，用途预算还差{money(f.get('unfunded_gap'))}。" if plan.get("available") else "先把数据问题核对清楚，再给借款金额。"),
            funding_steps=[dict(channel=c["name"], amount=c["amount"], months=c["months"], rate=c["rate"],
                cost=c["total_interest"]+c["total_fee"],
                reason=f"本次先尽量补足资金，同样覆盖金额下比较总利息和费用。已填容量{money(c['capacity'])}，期限{c['months']}个月；在用途和还款能力允许范围内参与组合选择。") for c in chosen])
        if plan.get("public_basis") and plan.get("available"):
            result["summary"]=f"自主推导现金缺口{money(f.get('gap'))}；可配置新增借款预算{money(f.get('debt_total'))}；仍需非债务资金或缩减用途{money(f.get('unfunded_gap'))}。"
            for step in result["funding_steps"]:
                step["reason"]="按公开数据推导的现金缺口、现金压力、杠杆与用途期限匹配求解；该期限金额是数学预算，没有输入或推定企业实际授信。费用未纳入。"
        if plan.get("sme_basis") and plan.get("available"):
            result["summary"]=f"您想借{money(f['gap'])}；在本轮用途、产品边界及现金压力下，拟申请{money(f['debt_total'])}，还差{money(f['unfunded_gap'])}需要调整支出。"
            for step in result["funding_steps"]:step["reason"]="匹配公开产品边界并通过财务预算约束；这是拟申请金额，企业准入、担保和报价还需受理机构确认。"
    return result


def focus_markdown(focus):
    lines=["## 本次分析重点："+focus["goal"], focus["title"], focus["summary"]]
    for step in focus.get("funding_steps", []):
        lines.append(f"- {step['channel']}：{money(step['amount'])}；假设利息与费用合计{money(step['cost'])}。{step['reason']}")
    risk=focus.get("risk")
    if risk:
        lines.extend(f"- {r['question']}：{r['level']}；{r['reason']}" for r in risk["ranked"])
        t=risk["threshold"]
        if t:
            lines.append(f"加息假设下，本组合每年至少需要{money(t['minimum_cash'])}还款现金，才能达到{t['target']:.2f}的项目安全线。")
            lines.append("年度还款现金已低于安全线。" if t["already_below"] else f"年度还款现金最多可下降{t['cash_drop_limit']:.1%}触及安全线。" if t["cash_drop_limit"] is not None else "无正还款负担或正现金基准，不能给出下降临界比例。")
            lines.extend([f"要通过设定的{t['planned_drop']:.0%}现金下降情景：至少增加年度可还款现金{money(t['cash_improvement'])}，或减少对应年度本息{money(t['service_reduction'])}；两者是替代测算，不能重复计入。", t["note"]])
        for d in risk["improvements"]:
            lines.append(f"- 改善试算：{d['title']}，对应{(money(d['value']) if d['unit'] == '元' else str(round(d['value'], 2)) + d['unit'])}对应的敏感性结果；不是已到账现金。{d['action']}")
        lines.append(risk["scope"])
    comparison=focus.get("comparison")
    if comparison:
        lines.extend(["| 方案 | 新增借款 | 用途缺口 | 全期限利息及费用 | "+("新增还款峰值（12个月）" if focus.get("sme_basis") else "加息后新增12个月本息")+" | 统一压力覆盖率 |", "| --- | --- | --- | --- | --- | --- |"])
        for p in comparison["options"]:
            dscr=f"{p['common_stress_dscr']:.2f}" if p["common_stress_dscr"] is not None else "无本息负担"
            lines.append(f"| {p['title']} | {money(p['debt'])} | {money(p['gap'])} | {money(p['total_cost'])} | {money(p['new_service'])} | {dscr} |")
            # Append explanations after the complete table below.
        for p in comparison["options"]:
            lines.extend(["- "+p["title"]+"："+p["reason"]+" "+p["status"], "渠道分配："+("；".join(c["name"]+money(c["amount"])+f"，{c['months']}个月" for c in p["composition"]) or "无新增借款")])
        lines.extend(comparison["duplicates"]+[comparison["note"]])
    merged=[]
    for line in lines:
        if line.startswith("| ") and merged and merged[-1].startswith("| "):
            merged[-1]+="\n"+line
        else:
            merged.append(line)
    return merged
