"""Public-report tenor optimization; ceilings are estimates, never bank limits."""
from finbridge.public_finance import public_model
from finbridge.portfolio import _optimize, _service_factor
from finbridge.decision import annual_annuity_factor


def build_public_portfolio(data,profile,planning_stress=None,selection_objective="cost"):
    if profile.get("decision_engine")=="enterprise-v3":
        from finbridge.enterprise_model import optimize_financing
        return optimize_financing(data,profile,planning_stress,selection_objective)
    if profile.get("requested_amount") is not None:
        from finbridge.sme_decision import build_sme_portfolio
        return build_sme_portfolio(data,profile,planning_stress,selection_objective)
    m=public_model(data,profile);a=m["assumptions"];ready=m["available"]
    stress=planning_stress or {"cash_drop":a["cash_drop"],"rate_up":a["rate_up"]}
    if not .2<=stress["cash_drop"]<=.4 or not .01<=stress["rate_up"]<=.05:
        raise ValueError("公开数据压力假设超出支持范围")
    if selection_objective not in {"cost","repayment"}:raise ValueError("优化目标无效")
    need,own,gap=(m[k] for k in ("need","internal","gap")) if ready else (None,None,None)
    target=a["target_coverage"];months=[12,24,36,60];rate=a["assumed_rate"]
    names=[f"{n}个月分期借款预算" for n in months]
    leverage=max(0,(a["max_leverage"]*data["total_assets"]-data["total_liabilities"])/(1-a["max_leverage"])) if ready else 0.
    cash=m.get("cash",0.);existing=m.get("service",0.)
    stressed=cash*(1-stress["cash_drop"]) if cash>=0 else cash*(1+stress["cash_drop"])
    budget=max(0,stressed/target-existing) if ready else 0.
    factors=[_service_factor(rate+stress["rate_up"],n) for n in months]
    costs=[annual_annuity_factor(rate,n)/12*n-1 for n in months]
    amounts,checked,constraints=_optimize([gap]*4,factors,factors if selection_objective=="repayment" else costs,
        min(gap,leverage),budget,m["working_gap"],m["equipment_gap"]) if ready else ([0.]*4,0,[])
    composition=[]
    for i,(name,n,amount) in enumerate(zip(names,months,amounts)):
        composition.append(dict(id=("credit","receivable","secured","leasing")[i],name=name,months=n,rate=rate,fee_rate=0.,
            amount=amount if ready else None,capacity=gap,share=amount/sum(amounts) if sum(amounts)>0 else 0.,
            total_interest=amount*costs[i] if ready else None,total_fee=0.,monthly_payment=amount*annual_annuity_factor(rate,n)/12,
            reason="按公开报表现金需求、现金压力和杠杆边界选择期限；长期借款可减轻近期本息，但增加全期限利息。",assumed=["利率为情景输入；费用未纳入，不代表实际免费。"],enabled=True,capacity_input="financing_need"))
    debt=sum(amounts) if ready else None
    funding=dict(need=need,internal_used=own,gap=gap,debt_total=debt,unfunded_gap=max(0,gap-debt) if ready else None,
        fees_due=0. if ready else None,fee_funding_gap=0. if ready else None,total_unfunded_cash=max(0,gap-debt) if ready else None,
        total_assumed_interest=sum(c["total_interest"] for c in composition) if ready else None,
        note="资金用途、内部现金来源、到期本息均为公开报表推导的情景估算。金额是数学预算，不是可用授信；费用未纳入。")
    scenarios=[]
    if ready:
        for key,label,drop,up in (("base","基准情景",0.,0.),("cash_drop","还款现金代理下降",stress["cash_drop"],0.),
            ("rate_up","利率上行情景",0.,stress["rate_up"]),("double","双重压力",stress["cash_drop"],stress["rate_up"]),("cash_drop_30","额外探索：现金代理下降30%",.3,0.)):
            cf=cash*(1-drop) if cash>=0 else cash*(1+drop)
            service=sum(c["amount"]*_service_factor(rate+up,c["months"]) for c in composition)
            total=existing+service
            scenarios.append(dict(id=key,label=label,cfads=cf,new_annual_service=service,existing_annual_service=existing,
                dscr=cf/total if total>0 else None,gap_to_target=max(0,target*total-cf),cash_drop=drop,rate_up=up))
    for c in constraints:
        c["used"]=sum(x*y for x,y in zip(c["coefficients"],amounts));c["remaining"]=c["limit"]-c["used"]
        if c["id"] in {"credit_limit","receivable_limit","secured_limit","leasing_limit"}:
            c["label"]=names[("credit_limit","receivable_limit","secured_limit","leasing_limit").index(c["id"])]+"数学上限"
        elif c["id"]=="gap":c["label"]="现金缺口与情景杠杆共同上限"
        elif c["id"]=="working_purpose":c["label"]="12/24个月借款不超过非投资用途剩余缺口"
        elif c["id"]=="equipment_purpose":c["label"]="60个月借款不超过投资用途缺口"
    flags=[m["note"],"本金到期压力来自余额代理，没有合同日程；本结果不能声称验证了真实DSCR或月内现金安全。"]
    if not ready:flags += ["缺少公开科目："+"、".join(m["missing"]),*m["issues"]]
    algorithm=dict(name="公开报表现金需求模型＋四期限线性规划＋现金压力与杠杆约束",selection_objective=selection_objective,
        objective=["先最大覆盖现金缺口","同等覆盖下最小化假设总利息" if selection_objective=="cost" else "同等覆盖下最小化一年内加息本息"],
        checked_candidates=checked,target_dscr=target,planning_stress=stress,service_budget=budget,constraints=constraints,
        leverage_capacity=leverage,assumptions=["增长、利率、留存天数、杠杆上限、维持性开支占比是情景假设，不是企业内部数据。","等额本息；未建模审批、税盾、费用和月度季节性。"])
    return dict(public_basis=True,available=ready,status="公开数据条件预算" if ready else "公开科目不足，暂停金额求解",funding=funding,
        composition=composition,scenarios=scenarios,algorithm=algorithm,risk_flags=flags,alternatives=[],recommendations=[],
        repayment_note="覆盖倍数的现金和存量本息均含公开数据代理估算，不等同真实合同DSCR。",model=m)


def verify_public_plan(plan):
    if plan.get("engine")=="enterprise-v3":
        from finbridge.enterprise_model import verify_plan
        return verify_plan(plan)
    if plan.get("sme_basis"):
        from finbridge.sme_decision import verify_sme_plan
        return verify_sme_plan(plan)
    if not plan.get("available"):
        return dict(status="未验证",passed=False,checks=[],note="公开科目不足或矛盾，不能给出通过结论。")
    m=plan["model"];f=plan["funding"];a=plan["algorithm"];rows=[]
    def check(label,value,limit):
        rows.append(dict(label=label,value=value,limit=limit,passed=value<=limit+max(.02,abs(limit)*1e-8)))
    total=sum(c["amount"] for c in plan["composition"])
    check("各期限借款均不为负",-min(c["amount"] for c in plan["composition"]),0.)
    check("借款明细与本金汇总一致",abs(total-f["debt_total"]),.01)
    check("借款合计不超过现金缺口",total,f["gap"])
    check("借款合计不超过杠杆情景上限",total,a["leverage_capacity"])
    check("60个月借款不超过投资用途缺口",sum(c["amount"] for c in plan["composition"] if c["months"]==60),m["equipment_gap"])
    check("12/24个月借款不超过非投资用途缺口",sum(c["amount"] for c in plan["composition"] if c["months"]<=24),m["working_gap"])
    service=0.
    for c in plan["composition"]:
        rate=(c["rate"]+a["planning_stress"]["rate_up"])/12
        factor=1/c["months"] if rate==0 else rate/(1-(1+rate)**(-c["months"]))
        service+=c["amount"]*factor*min(12,c["months"])
    check("独立复算新增一年内本息不超过预算",service,a["service_budget"])
    stresscash=m["cash"]*(1-a["planning_stress"]["cash_drop"]) if m["cash"]>=0 else m["cash"]*(1+a["planning_stress"]["cash_drop"])
    check("整体本息达到现金安全线",a["target_dscr"]*(service+m["service"]),stresscash)
    check("资金来源、借款和缺口加总一致",abs(f["internal_used"]+total+f["unfunded_gap"]-f["need"]),.01)
    return dict(status="通过本次数学验证" if all(r["passed"] for r in rows) else "存在未通过的压力边界",passed=all(r["passed"] for r in rows),checks=rows,
        note="验证只证明输入和假设下的算术、约束与安全线，不证明预测准确或银行可批准。")
