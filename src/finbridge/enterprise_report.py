"""A concise decision brief, not a copy of three detailed analysis pages."""
from finbridge.result_review import money


def enterprise_report_markdown(run):
    if run.get('input_profile',{}).get('decision_scope')=='working-capital-12m':return annual_report_markdown(run)
    r=run.get("decision_report")
    if not r:return "# 企业财务与融资决策报告\n\n分析未完成，请查看财报核验及工具记录。"
    d=r["decision"];raw=run["raw_public"]
    sections=["# 企业财务与融资决策报告",
        f"{raw['company_name']} · {raw['industry']} · {raw['region']} · {raw['report_period']}",
        f"分析版本：{run['id']} · {run['created_at']} · {run['mode']}",
        "## 决策结论",r["title"],r["conclusion"],
        f"扣费后资金 {money(d['net'])}；尚未覆盖 {money(d['gap'])}；全期利息与费用 {money(d['interest']+d['fees'])}。",
        "## 财务判断"]
    for x in r["financial_takeaways"]:sections.extend(["### "+x["title"],x["finding"],x["implication"]])
    sections.append("## 融资策略")
    sections.extend(f"- {x['name']}：本金{money(x['amount'])}，{x['months']}个月。" for x in d["products"])
    if not d["products"]:sections.append("当前条件不支持新增债务，先处理现金偿付或资产池限制。")
    sections.extend(["## 风险与执行条件",r["risk"].get("reverse") or "未形成有效风险结果。",
        "独立验证："+r["verification"]["status"]+"。"+r["verification"]["note"],
        "95% CVaR尾部现金缺口："+money(r["risk"].get("cvar"))+"。这是假设路径结果，不是真实违约概率。",
        "## 下一步",*r["actions"],"## 计算边界",*r["assumptions"],r["note"],
        "MILP使用整数产品启用变量，CVaR使用最差5%情景平均现金储备缺口；独立风险检验3000条路径。种子和全部工具输出保存在验证证据包。"])
    ctx=run["outputs"].get("analyze_industry_region",{})
    sections.extend(["## 市场依据",str(ctx.get("summary") or ctx.get("source_status") or "本次未取得有效近期市场证据。")])
    for s in ctx.get("sources",[])[:6]:sections.append(f"{s.get('title',s.get('id'))} · {s.get('published_at','未核验日期')} · {s.get('url','')}")
    if run.get("conversation_adjustment"):
        sections.extend(["## 本次版本更新","用户确认的修改："+run["conversation_adjustment"]["question"],"此前版本："+run["conversation_adjustment"]["parent_run_id"]])
    return "\n\n".join(sections)


def annual_report_markdown(run):
    r=run.get('decision_report') or {};raw=run['raw_public'];d=r.get('decision',{});prediction=(run.get('financial_analysis',{}).get('forecast') or {}).get('history_prediction') or {};future=prediction.get('future') or {};validation=prediction.get('validation') or {}
    lines=['# 一年期生产经营周转融资报告',f"{raw['company_name']} · {raw['report_period']} · 规划年度{future.get('target_year','待确认')}",'期限12个月；用途生产经营周转。',r.get('title','分析未完成'),r.get('conclusion','')]
    lines += ['## 财务判断']+[x['title']+'：'+x['finding'] for x in r.get('financial_takeaways',[])]
    lines += ['## 现金预测与误差校正',f"历史预测{money(validation.get('annual_operating'))}；实际{money(validation.get('actual'))}；有符号误差{money(validation.get('error'))}。",f"下一年原始预测{money(future.get('uncalibrated_operating'))}；校正额{money(future.get('calibration_adjustment'))}；校正后{money(future.get('annual_operating'))}。",future.get('calibration_method','未校正')]
    lines += ['## 唯一推荐组合',f"净融资需求{money(run['input_profile']['requested_amount'])}；扣费后净资金{money(d.get('net'))}；未覆盖{money(d.get('gap'))}。"]
    lines += [f"{x['name']}：本金{money(x['amount'])}，期限{x['months']}个月。" for x in d.get('products',[])]
    lines += [f"一年利息{money(d.get('interest'))}；费用{money(d.get('fees'))}。",'## 风险情景与规则']
    for s in r.get('risk_scenarios',[]):lines += [s['label']+'：'+s['rule'],f"还款现金{money(s['annual_cash'])}；新旧本息{money(s['total_service'])}；安全线缺口{money(s['gap_to_target'])}；{'通过' if s['passed'] else '需调整'}。",'参数依据：'+s['parameter_origin']]
    risk=run['outputs']['assess_risk']['enterprise_risk']
    lines += ['## 情景CVaR辅助指标',f"CVaR{risk.get('cvar_alpha',.8):.0%}：{money(risk.get('cvar'))}。最差{1-risk.get('cvar_alpha',.8):.0%}等权情景的平均偿债后现金余量下降，不是现金不足额或实际概率。第二阶段目标为一年成本＋{risk.get('cvar_weight',.1)}×该值；硬约束保持。"]
    lines += ['## 执行条件',r.get('verification',{}).get('status','未验证'),*r.get('actions',[]),'## 模型边界',*r.get('assumptions',[]),'一次历史误差检验不足以证明预测准确。账面资产不是银行认可抵押物，已有债务到期是财报代理；保理需核实真实账期，不默认续作。']
    return '\n\n'.join(lines)
