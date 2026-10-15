"""Decision brief for reviewers; independent of the interactive financing workspace."""
from finbridge.market_rules import effective_portfolio
from finbridge.task_focus import build_task_focus
from finbridge.result_review import build_result_review, money

QUESTIONS = {
    "融资组合": "这笔资金怎么筹，能筹多少，还差多少，为什么这样安排？",
    "风险分析": "企业最容易在哪些地方出问题，还款能扛多大压力，先改善什么？",
    "方案比较": "不同借法各有什么代价，资金覆盖、还款压力和成本如何取舍？",
}
METRICS = {
    "融资组合": ("working_capital", "cash_conversion_cycle", "debt_to_asset_ratio", "dscr"),
    "风险分析": ("current_ratio", "debt_to_asset_ratio", "operating_cash_flow_margin", "dscr", "overdue_receivables_ratio"),
    "方案比较": ("cash_conversion_cycle", "debt_to_asset_ratio", "interest_coverage", "dscr"),
}
WHY = {
    "working_capital": "看流动资产减去流动负债后还剩多少周转余量。",
    "cash_conversion_cycle": "看从垫钱到收回现金大约需要多少天。",
    "debt_to_asset_ratio": "看资产中有多少由负债支撑；单独看它不能决定能否借款。",
    "dscr": "这里只看上传的原有偿债计划；新增借款后的压力结果另列。",
    "current_ratio": "看短期资产对短期负债的覆盖，仍要核实能否及时变现。",
    "operating_cash_flow_margin": "看销售收入有多少转化为经营净现金。",
    "overdue_receivables_ratio": "看客户拖欠的应收款占比，辅助判断回款问题。",
    "interest_coverage": "看利润能否覆盖利息，不代表本金也能还上。",
}


def build_report_brief(run):
    from finbridge.workflow import fmt
    out, data, profile = run["outputs"], run["data"], run["profile"]
    plan = effective_portfolio(out) or {}
    focus = out["prepare_deliverables"].get("task_focus") or build_task_focus(data, profile, out, run["goal"])
    risk = focus.get("risk") or build_task_focus(data, profile, out, "风险分析").get("risk", {})
    f = plan.get("funding", {})
    review = build_result_review(run)
    metrics = []
    for key in METRICS[run["goal"]]:
        m = out["calculate_ratios"].get(key)
        if m:
            metrics.append(dict(label=m["label"], value=fmt(m["value"], m["unit"]), why=WHY[key],
                formula=m["formula"], issue=m.get("data_issue") or "", sources=m["sources"]))
    ranked = risk.get("ranked", [])
    material = [r for r in ranked if r["level"] in {"较高", "关注", "无法判断"}]
    risks = material[:3] or ranked[:2]
    if not plan.get("available"):
        conclusion = "当前数据不足或存在矛盾，暂不能形成可靠的借款金额；先修正数据，再重新分析。"
    elif run["goal"] == "融资组合":
        conclusion = focus["summary"] + "一次性费用另需" + money(f.get("fees_due")) + "。"
    elif run["goal"] == "风险分析":
        conclusion = focus["summary"]
        t = risk.get("threshold")
        if t:
            conclusion += "加息假设下，每年至少需" + money(t["minimum_cash"]) + "还款现金。"
    else:
        options = focus.get("comparison", {}).get("options", [])
        conclusion = focus["summary"]
        if len(options) > 1:
            a, b = options[0], options[-1]
            conclusion += "相比“"+a["title"]+"”，“"+b["title"]+"”的借款金额差"+money(b["debt"]-a["debt"])+"，一年内新增还款差"+money(b["new_service"]-a["new_service"])+"（后者减前者）。"
    strategies = []
    if run["goal"] == "融资组合":
        chosen = focus.get("funding_steps", [])
        strategies.append(dict(title="按用途落实渠道", detail="；".join(s["channel"]+money(s["amount"]) for s in chosen) or "当前没有可配置的新增借款，先核对渠道容量及还款条件。"))
        strategies.append(dict(title="把剩余缺口和费用单独安排", detail="用途缺口"+money(f.get("unfunded_gap"))+"，一次性费用"+money(f.get("fees_due"))+"；优先核实能否增加真实自有资金，或延后非必要支出，不能默认再借一笔。"))
    elif run["goal"] == "风险分析":
        t = risk.get("threshold")
        if t:
            if t["cash_improvement"] > .01:
                strategies.append(dict(title="先把还款余量留出来", detail="通过设定压力情景还需增加年度还款现金"+money(t["cash_improvement"])+"，或减少对应年度本息"+money(t["service_reduction"])+"；是两条替代路径，不能相加。"))
            else:
                strategies.append(dict(title="保住已有的还款余量", detail="当前组合已满足设定的压力线，不需为通过这条线额外改善现金；仍应跟踪回款和到期本息，不要把测算通过理解为可以继续叠加借款。"))
        for d in [d for d in risk.get("improvements", []) if d["unit"] == "元"][:2]:
            strategies.append(dict(title=d["title"], detail=money(d["value"])+"的条件试算；"+d["action"]+" 需验证能否兑现，不能当作已到账。"))
    else:
        for p in focus.get("comparison", {}).get("options", []):
            strategies.append(dict(title=p["title"], detail=p["reason"]+" 用途还差"+money(p["gap"])+"；"+p["status"]+"。"))
    if not plan.get("available"):
        strategies = [dict(title="先修正输入，再判断借法", detail="；".join(review["causes"]) or "补齐年度现金流、存量偿债计划及渠道条件。")]
    context = out.get("analyze_industry_region", {})
    decision = context.get("market_decision") or {}
    market = dict(changed=bool(decision.get("changed")), status=context.get("status", "未生成"), summary=context.get("summary", "本次没有合格的行业地区分析。"),
        impact=decision.get("action") or "没有可用于调整组合的已核验市场信号；不能据此判断市场没有风险。",
        source_status=context.get("source_status", "未取得可核验资料"),
        sources=[dict(id=s["id"], title=s["title"], url=s["url"], date=s["published_at"]) for s in context.get("sources", [])],
        evidence=[dict(title=i["title"], analysis=i["analysis"], source_ids=i.get("source_ids", []), basis=i.get("basis", ""))
            for key in ("implications", "actions") for i in context.get("sections", {}).get(key, [])][:2])
    return dict(goal=run["goal"], question=QUESTIONS[run["goal"]], conclusion=conclusion, title=focus["title"],
        company=data.get("company_name", "未命名企业"), industry=profile.get("industry", "未提供"), region=profile.get("region", "未提供"),
        period=data.get("report_period", "未提供"), source=run["source"], available=bool(plan.get("available")),
        request=dict(need=profile["amount"], own=profile["internal_funds"], months=profile["months"], purpose=profile["purpose"]),
        funding=f, metrics=metrics, risks=risks, strategies=strategies, threshold=risk.get("threshold"),
        scenarios=[s for s in plan.get("scenarios", []) if s["id"] in {"base", "double", "cash_drop_30"}],
        channels=focus.get("funding_steps", []), comparison=focus.get("comparison"), market=market,
        methods="校验上传数据 → Python计算财务指标 → 规则筛查风险 → 约束优化求解融资组合 → 压力测试；开启AI时再进行近期资料检索、来源核验与模型解释。",
        boundary="这是条件测算，未承诺银行审批或真实报价；年度数据不能证明每个月都能按时还款。模拟数据不代表真实企业。")


def brief_markdown(brief):
    from finbridge.workflow import fmt
    b = brief
    lines = ["## 本次分析速览", "**这次要解决的问题：**"+b["question"],
        f"对象：{b['company']}；{b['industry']} · {b['region']}；报告期：{b['period']}；数据来源：{b['source']}。",
        "需求："+money(b["request"]["need"])+"；自有资金："+money(b["request"]["own"])+f"；期限：{b['request']['months']}个月；用途：{b['request']['purpose']}。",
        "### 本次分析重点："+b["goal"], b["title"], b["conclusion"], "### 支撑结论的关键指标"]
    lines += ["- "+m["label"]+"："+m["value"]+"；"+m["why"]+(" 未计算原因："+m["issue"] if m["issue"] else "") for m in b["metrics"]]
    if b["channels"]:
        lines.append("### 筹资安排")
        lines += ["- "+s["channel"]+"："+money(s["amount"])+f"，{s['months']}个月；假设利息及费用"+money(s["cost"])+"。" for s in b["channels"]]
    if b["comparison"]:
        lines.append("### 不同方案的取舍")
        lines += ["- "+p["title"]+"：借款"+money(p["debt"])+"；缺口"+money(p["gap"])+"；全期限成本"+money(p["total_cost"])+"；加息后新增一年内本息"+money(p["new_service"])+"；统一压力覆盖倍数"+fmt(p["common_stress_dscr"], "倍")+"。" for p in b["comparison"]["options"]]
        lines += b["comparison"]["duplicates"]
    lines.append("### 最需要注意的风险")
    lines += ["- "+r["question"]+"："+r["level"]+"；"+r["reason"] for r in b["risks"]]
    lines.append("### 压力下还能不能还款")
    lines += ["- "+s["label"]+"：年度还款现金"+money(s["cfads"])+"，一年内合计本息"+money(s["new_annual_service"]+s["existing_annual_service"])+"，覆盖"+fmt(s["dscr"], "倍")+"；达到安全线还需年度现金"+money(s["gap_to_target"])+"。" for s in b["scenarios"]]
    if not b["scenarios"]:
        lines.append("输入未齐备或未通过核验，暂不能验证偿付能力。")
    lines.extend(["### 下一步策略", *["- "+s["title"]+"："+s["detail"] for s in b["strategies"]],
        "### 近期市场对结论的影响", b["market"]["source_status"], b["market"]["impact"]])
    lines += ["- "+i["title"]+"："+i["analysis"]+"（"+("、".join(i["source_ids"]) or "模型判断，无来源支持")+"）" for i in b["market"]["evidence"]]
    lines.extend(["### 本次使用的方法与结论边界", b["methods"], b["boundary"]])
    return lines
