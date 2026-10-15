"""Public-data report: raw facts, formula models and assumptions stay separate."""
from finbridge.market_rules import effective_portfolio
from finbridge.public_data import PUBLIC_LABELS
from finbridge.task_focus import focus_markdown
from finbridge.result_review import money


def public_report_markdown(run):
    if run.get("decision_engine")=="enterprise-v3":
        from finbridge.enterprise_report import enterprise_report_markdown
        return enterprise_report_markdown(run)
    out=run["outputs"];m=run["public_analysis"];p=effective_portfolio(out)
    if not p or "prepare_deliverables" not in out:
        return "# 公开报表决策历史快照\n\n该任务缺少完整求解或交付结果，不能生成肯定融资结论。请重新执行。"
    f=p["funding"]
    d=out["prepare_deliverables"];v=out.get("verify_decision",{})
    raw=run["raw_public"]
    lines=["# 融智 · 公开财务报表融资决策报告",f"企业：{raw.get('company_name')}；报告期：{raw.get('report_period')}；任务：{run['goal']}",
        f"编号：{run['id']}；时间：{run['created_at']}；执行模式：{run['mode']}",
        "## 这次分析在做什么","只使用公开报表原值，自动推导下一年度现金需求情景，求解不同期限的借款预算，并独立验证还款压力。",
        "## 先看核心结论",d["task_focus"]["summary"],
        "自主推导外部现金缺口："+money(f.get("gap"))+"；可配置借款预算："+money(f.get("debt_total"))+"；仍需非债务资金或缩减用途："+money(f.get("unfunded_gap"))+"。",
        "验证结果："+v.get("status","未验证"),m["note"]]
    if p.get("sme_basis"):
        review=out.get("review_financing_request",p["request_review"])
        from finbridge.sme_decision import recommended_portfolio
        original_f=f
        p=recommended_portfolio(out);f=p["funding"]
        v=d.get("recommended_verification",v)
        lines=["# 融智 · 中小微与科创企业融资决策报告",f"企业：{raw.get('company_name')}；报告期：{raw.get('report_period')}；分析重点：{run['goal']}",
            f"任务：{run['id']}；生成时间：{run['created_at']}；模式：{run['mode']}",
            "## 本次在解决什么问题",f"企业希望借{money(review['requested_amount'])}，用于{review['purpose']}，{review['requested_months']}个月归还。分析先检查需求是否与财务能力匹配，再安排拟申请渠道，验证压力并复审调整。",
            "## 一分钟看懂结论",review["status"],*review["reasons"],
            "按原期限可配置拟申请金额："+money(original_f["debt_total"])+"。最终建议采用"+d.get("recommended_from","本轮方案")+"：拟申请"+money(f["debt_total"])+"；先缩减或延后"+money(f["unfunded_gap"])+"。",
            "验证结果："+v.get("status","未验证")]
        alternate=review.get("alternative")
        if alternate:
            lines += ["## 需求不匹配时的替代方案",alternate["explanation"],"调整方案独立验证："+("通过，产品准入仍待核验" if alternate.get("verified") else "未通过，暂无安全新增债务方案")]
            for c in alternate.get("composition",[]):lines.append("- "+c["name"]+"：拟申请"+money(c["amount"])+f"，{c['months']}个月。")
        lines += ["## 拟申请渠道与落地条件"]
        for c in p["composition"]:
            if (c.get("amount") or 0)>0:
                lines.append("- "+c["name"]+"：拟申请"+money(c["amount"])+f"，{c['months']}个月；假设全期利息"+money(c["total_interest"])+"。")
                lines += ["需确认："+"、".join(c["conditions"])+"；"+c["published_terms"],"官方办理参考：["+c["name"]+"]("+c["url"]+")；核验日期："+c["checked_on"]]
        lines += ["用户需求是外部借款金额，不再重复扣除账上现金。官方产品上限不是企业可用额度；实际利率、费用和准入仍待机构核验。",p["repayment_note"]]
        lines += ["## 财务状况，用大白话看"]+["- "+x["question"]+"："+x["evidence"]+"。"+x["conclusion"] for x in out["assess_risk"].get("plain_summary",[])]
    if not m["available"]:
        lines += ["缺少公开科目："+"、".join(PUBLIC_LABELS.get(k,k) for k in m["missing"]),*m["issues"]]
    lines += [line.replace("利息及费用","假设利息（未含费用）").replace("利息与费用","假设利息（未含费用）").replace("全期限成本","全期限假设利息（未含费用）") for line in focus_markdown(d["task_focus"])]
    lines += ["## 核心财务指标"]
    if run.get("conversation_adjustment"):
        lines += ["本版由金融决策对话触发重新求解，原始财报未改变。父版本："+run["conversation_adjustment"]["parent_run_id"],"用户本轮问题："+run["conversation_adjustment"]["question"]]
    from finbridge.workflow import fmt
    keys=("current_ratio","debt_to_asset_ratio","gross_profit_margin","net_profit_margin","receivables_days","inventory_days","cash_conversion_cycle","operating_cash_flow_margin")
    for key in keys:
        metric=out["calculate_ratios"].get(key)
        if metric:lines.append("- "+metric["label"]+"："+fmt(metric["value"],metric["unit"])+"；"+metric["formula"]+("；"+metric["data_issue"] if metric.get("data_issue") else ""))
    lines += ["## 风险验证与压力测试","以下覆盖倍数的现金和已有本息都是模型代理情景；不声称已经取得真实合同DSCR。"]
    for s in p.get("scenarios",[]):
        lines.append("- "+s["label"]+"：现金代理"+money(s["cfads"])+("，已有及新增最重12个月本息" if p.get("sme_basis") else "，已有及新增一年内本息")+money(s["new_annual_service"]+s["existing_annual_service"])+"，覆盖倍数"+fmt(s["dscr"],"倍")+"，距安全线还需年度现金"+money(s["gap_to_target"])+"。")
    for c in v.get("checks",[]):
        lines.append("- "+c["label"]+"："+("通过" if c["passed"] else "未通过")+"；复算值"+money(c["value"])+"，边界"+money(c["limit"])+"。")
    lines += ["## 下一步策略"]
    if f.get("unfunded_gap",0):lines.append("先处理未覆盖现金缺口："+money(f["unfunded_gap"])+"。可以试算减少资本开支、降低增长占款、增加现金留存或改变期限；不能默认增加借款或股权融资能落地。")
    for t in d["tasks"]:lines.append("- "+t["title"]+"；依据："+t["evidence"])
    ctx=out.get("analyze_industry_region",{})
    lines += ["## 行业地区与近期市场",ctx.get("summary","未启用AI检索"),ctx.get("source_status","没有可核验资料")]
    decision=ctx.get("market_decision",{})
    lines.append(decision.get("action","本次未取得用于调整参数的市场信号；不能据此认定市场无风险。"))
    for key,items in ctx.get("sections",{}).items():
        for item in items:lines.append("- "+item["title"]+"："+item["analysis"]+"；来源："+("、".join(item.get("source_ids",[])) or "模型判断"))
    for s in ctx.get("sources",[]):lines.append(f"- {s['id']} {s['title']}；日期：{s['published_at']}；{s['url']}")
    lines += ["## 情景假设（与公开事实分开）"]
    for key,value in m["assumptions"].items():lines.append(f"- {key}：{value}")
    lines += ["## 附录：每个模型结果如何算出来"]
    for e in m["ledger"]:lines.append("- "+e["label"]+"："+(fmt(e["value"],"%") if e["key"]=="growth" else money(e["value"]))+"；"+e["formula"]+"；来源："+"、".join(e["sources"])+"；类型："+e["kind"])
    lines += ["## 附录：公开输入与来源"]
    for key,label in PUBLIC_LABELS.items():
        if raw.get(key) is not None:
            ref=raw.get("public_provenance",{}).get(key,{}) if isinstance(raw.get("public_provenance"),dict) else {}
            lines.append("- "+label+"："+money(raw[key])+"；"+str(ref or raw.get("public_source","用户未填写公开来源")))
    lines += ["## 适用边界",*d["limitations"],"融资结构为官方产品边界下的条件式拟申请测算，企业资格尚未确认；费用未纳入，不能当作实际免费。" if p.get("sme_basis") else "融资结构只比较假设期限，不是银行产品；费用未纳入，不能当作实际免费。"]
    return "\n\n".join(lines)
