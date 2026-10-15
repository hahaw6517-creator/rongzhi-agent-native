"""SME requested financing: product-constrained LP, demand review and independent verification."""
from copy import deepcopy
from finbridge.portfolio import _optimize
from finbridge.public_finance import public_model
from finbridge.sme_channels import match_sme_channels
from finbridge.result_review import money


def peak_service_factor(rate,months,repayment):
    """Conservative maximum rolling-12-month service over the WHOLE loan term."""
    if repayment=="bullet":return 1+rate*months/12
    count=min(12,months)
    return count/months+rate/12*sum(1-i/months for i in range(count))


def total_interest_factor(rate,months,repayment):
    return rate*months/12 if repayment=="bullet" else rate*(months+1)/24


def target_scope(data):
    industry=str(data.get("industry", ""))
    # This MVP intentionally covers two cash-cycle families; a label alone is no certification.
    return any(k in industry for k in ("制造","加工","机械","设备","电子","半导体","材料","医药","生物","软件","信息技术","信息服务","互联网","集成电路"))


def sector_model(data,profile):
    software=any(k in str(data.get("industry","")) for k in ("软件","信息技术","信息服务","互联网"))
    return dict(key="software" if software else "manufacturing",label="软件与信息技术：先看回款与研发现金" if software else "制造类：先看库存、账期与设备投入",
        priority_metrics=["receivables_days","operating_cash_flow_margin","net_profit_margin"] if software else ["cash_conversion_cycle","inventory_days","gross_profit_margin","debt_to_asset_ratio"],
        interpretation="轻资产并不等于还款能力弱；重点看应收是否变成现金。研发没有稳定经营现金支撑时，不能仅凭利润建议增加债务。" if software else "订单增长可能压住应收和存货；周转借款与设备投资分开，设备优先匹配中长期分期偿还。",
        preference="先展示科创信用、合作平台及地方增信路径；抵押路径仅作需另核资产条件的备选。" if software else "比较周转信用、合作平台、抵押和设备分期产品；抵押价值与项目首付款均不从账面资产推断。")


def financial_health(data):
    rows=[]
    if data.get("revenue") and data.get("net_profit") is not None:
        margin=data["net_profit"]/data["revenue"]
        rows.append(dict(question="生意赚不赚钱",conclusion=("本期净亏损，借款不能替代经营改善。" if margin<0 else "本期有利润；还要看钱是否实际收回来。"),evidence=f"净利率{margin:.1%}"))
    if data.get("operating_cash_flow") is not None:
        cash=data["operating_cash_flow"]
        rows.append(dict(question="经营有没有带来现金",conclusion="经营现金流为负，先核对回款与经营占款，谨慎追加债务。" if cash<0 else "经营带来正现金，但已有债务、维持性支出还要扣除。",evidence="经营现金流"+money(cash)))
    if data.get("current_liabilities") and data.get("current_assets") is not None:
        ratio=data["current_assets"]/data["current_liabilities"]
        rows.append(dict(question="短期周转紧不紧",conclusion="流动资产少于流动负债，短期周转需要重点关注。" if ratio<1 else "账面流动资产覆盖流动负债；应收和存货不等于随时可用现金。",evidence=f"流动比率{ratio:.2f}倍"))
    if data.get("total_assets") and data.get("total_liabilities") is not None:
        ratio=data["total_liabilities"]/data["total_assets"]
        rows.append(dict(question="现在欠债有多重",conclusion="新增借款还需通过设定的负债率边界和现金压力；单凭资产规模不能判断贷多少。",evidence=f"资产负债率{ratio:.1%}"))
    return rows


def build_sme_portfolio(data,profile,planning_stress=None,selection_objective="cost"):
    m=public_model(data,profile);a=m["assumptions"]
    stress=planning_stress or dict(cash_drop=a["cash_drop"],rate_up=a["rate_up"])
    if not .2<=stress["cash_drop"]<=.4 or not .01<=stress["rate_up"]<=.05:raise ValueError("压力参数超出范围")
    if selection_objective not in {"cost","repayment"}:raise ValueError("优化目标无效")
    scope_ok=target_scope(data)
    ready=m["available"] and scope_ok
    request=profile["requested_amount"];purpose=profile.get("requested_purpose","经营周转");term=int(profile.get("requested_months",24))
    channels=match_sme_channels(data,profile)
    current_products=any(c["scope_match"] and c["source_current"] and c["max_months"] is not None for c in channels)
    ready=ready and current_products
    selected=[deepcopy(c) for c in channels[:4]]
    js_tech=next(c for c in channels if c["id"]=="boc_js_tech")
    if js_tech["scope_match"] and js_tech["source_current"]:
        selected[0]=deepcopy(js_tech);selected[0]["catalog_id"]="boc_js_tech";selected[0]["id"]="credit"
    local=next(c for c in channels if c["id"]=="sip_tech")
    if local["scope_match"] and local["source_current"]:
        # The local facility is an alternative to the platform facility, never stacked twice.
        selected[1]=deepcopy(local);selected[1]["catalog_id"]="sip_tech";selected[1]["id"]="receivable"
    rows=[]
    for c in selected:
        months=min(term,c["max_months"])
        cap=min(request,c["maximum"] if c["maximum"] is not None else request) if ready and c["scope_match"] and c["source_current"] and months>=c["min_months"] else 0.
        row=dict(c,months=months,capacity=cap,rate=a["assumed_rate"],fee_rate=0.,amount=0.,total_fee=0.,enabled=cap>0,
            capacity_input="财务预算与公开产品边界，未确认实际授信",assumed=["利率是假设，费用未纳入。","资格、抵押、自有资金要求及真实还款方式待机构核验。"])
        rows.append(row)
    cash=m.get("cash",0.);existing=m.get("service",0.)
    stressed=cash*(1-stress["cash_drop"]) if cash>=0 else cash*(1+stress["cash_drop"])
    budget=max(0,stressed/a["target_coverage"]-existing) if ready else 0.
    # Keep the reported asset base fixed: borrowing spent on R&D/expenses need not create assets.
    leverage=max(0,a["max_leverage"]*data["total_assets"]-data["total_liabilities"]) if ready else 0.
    equipment=request if purpose=="设备购置" else 0.;working=request-equipment
    factors=[peak_service_factor(c["rate"]+stress["rate_up"],c["months"],c["repayment"]) for c in rows]
    costs=[total_interest_factor(c["rate"],c["months"],c["repayment"]) for c in rows]
    amounts,checked,constraints=_optimize([c["capacity"] for c in rows],factors,factors if selection_objective=="repayment" else costs,
        min(request,leverage),budget,working,equipment) if ready else ([0.]*4,0,[])
    for c,amount,cost in zip(rows,amounts,costs):
        c.update(amount=amount if ready else None,total_interest=amount*cost if ready else None,share=amount/sum(amounts) if sum(amounts)>0 else 0.,
            monthly_payment=amount*(1/c["months"]+c["rate"]/12) if c["repayment"]=="equal_principal" else None,
            reason="先满足用途、期限和公开产品边界，再按现金抗压与负债上限分配拟申请金额；不是银行承诺。")
    scenarios=[]
    if ready:
        for key,label,drop,up in (("base","正常经营",0.,0.),("cash_drop","还款现金减少",stress["cash_drop"],0.),("rate_up","借款利率上升",0.,stress["rate_up"]),("double","现金减少＋利率上升",stress["cash_drop"],stress["rate_up"]),("cash_drop_30","额外检查：现金减少30%",.3,0.)):
            cf=cash*(1-drop) if cash>=0 else cash*(1+drop)
            service=sum(c["amount"]*peak_service_factor(c["rate"]+up,c["months"],c["repayment"]) for c in rows)
            total=existing+service
            scenarios.append(dict(id=key,label=label,cfads=cf,new_annual_service=service,existing_annual_service=existing,dscr=cf/total if total>0 else None,
                gap_to_target=max(0,a["target_coverage"]*total-cf),cash_drop=drop,rate_up=up))
    for c in constraints:
        c["used"]=sum(x*y for x,y in zip(c["coefficients"],amounts));c["remaining"]=c["limit"]-c["used"]
    debt=sum(amounts) if ready else None
    funding=dict(need=request,internal_used=0.,gap=request,debt_total=debt,unfunded_gap=max(0,request-debt) if ready else None,
        fees_due=0.,fee_funding_gap=0.,total_unfunded_cash=max(0,request-debt) if ready else None,
        total_assumed_interest=sum(c["total_interest"] for c in rows) if ready else None,
        note="需求是用户填写的外部借款额，已经扣除自行安排的资金；不重复扣除账上现金。拟申请金额须以银行审批及实际报价为准。费用未纳入。")
    algorithm=dict(name="中小微用途筛选＋官方产品边界＋双目标线性规划＋全期限偿付峰值检验",selection_objective=selection_objective,
        target_dscr=a["target_coverage"],planning_stress=stress,service_budget=budget,leverage_capacity=leverage,checked_candidates=checked,constraints=constraints,
        objective=["先尽量覆盖用户借款需求","同样金额下最小化假设总利息" if selection_objective=="cost" else "同样金额下最小化还款最重年份的本息"],
        assumptions=["未来各年还款现金按同一年度情景，不能当成预测。存量本息代理每年保守保留。","杠杆容量=max(0,报表资产×情景负债率上限－报表负债)，不假定新借款一定形成新增资产。","未知还款方式按到期一次还本付息保守检查，本息峰值含全期利息，不能默认续贷；分期产品按等额本金情景检查。"])
    plan=dict(public_basis=True,sme_basis=True,available=ready,status="财务条件下的拟申请方案 · 待机构准入核验" if ready else "暂不能形成融资方案",
        request_profile={k:profile.get(k,default) for k,default in (("requested_amount",request),("requested_months",24),("requested_purpose","经营周转"),("enterprise_type","中小微企业"))},
        funding=funding,composition=rows,scenarios=scenarios,algorithm=algorithm,model=m,channel_catalog=channels,
        risk_flags=[m["note"],"企业类型由用户选择，不等于法定中小微划型或科创认证；财报不能替代征信和产品准入。"]+([] if scope_ok else ["当前版本仅覆盖制造类及软件信息技术类；本行业尚未配置专门模型，请勿套用。"]) + ([] if current_products else ["匹配用途的产品资料已超过核验窗口或缺少期限信息，请更新官方来源后再求解；不能据此判断企业需求不合理。"]),
        sector_model=sector_model(data,profile),alternatives=[],recommendations=[],repayment_note="压力表使用各渠道全期限最重12个月本息的保守合计，不等于未来12个月真实合同DSCR。")
    plan["request_review"]=review_request(plan,profile)
    return plan


def review_request(plan,profile):
    request=profile["requested_amount"];term=int(profile.get("requested_months",24));purpose=profile.get("requested_purpose","经营周转")
    if not plan["available"]:
        return dict(status="先补齐数据、更新产品来源或选择支持行业",reasonable=None,requested_amount=request,requested_months=term,purpose=purpose,reasons=plan["risk_flags"],checks=[],alternative=None)
    a=plan["algorithm"];m=plan["model"];debt=plan["funding"]["debt_total"]
    factors=[peak_service_factor(c["rate"]+a["planning_stress"]["rate_up"],c["months"],c["repayment"]) for c in plan["composition"] if c["enabled"]]
    # Most favourable admissible product is still insufficient => original amount is definitely outside this screen.
    best_factor=min(factors) if factors else None
    request_service=request*best_factor if best_factor is not None else None
    full=debt>=request-.02
    checks=[dict(label="用途和期限有对应产品",passed=bool(factors),detail="有候选产品，准入尚待机构确认" if factors else "当前用途或期限没有可参与测算的产品"),
        dict(label="新增负债未超过杠杆安全边界",passed=request<=a["leverage_capacity"]+.01,detail="该边界为自设情景，不是银行统一准入标准"),
        dict(label="借款需求可在双重压力下覆盖",passed=full,detail="已按每个产品的还款峰值和公开边界求解，而非只看净利润"),
        dict(label="需求有公开历史现金用途参照",passed=request<=m["gap"]+.01,detail="高于历史情景不直接等于不合理，可能有新项目；本工具仅提示说明新增用途")]
    reasons=[]
    if not factors:reasons.append("当前用途或期限没有匹配产品；设备购置渠道通常需要更长还款期，不能拿短期周转贷硬凑。")
    if request>a["leverage_capacity"]+.01:reasons.append("这笔借款会超过设定的负债安全边界；按该边界新增负债最多"+money(a["leverage_capacity"])+"。")
    if not full:reasons.append("在现金减少与利率上升后，现有债务还要还；本轮最多配置"+money(debt)+"，比原需求少"+money(request-debt)+"。")
    if request>m["gap"]+.01:reasons.append("填写借款比历史财报推导的年度现金缺口高"+money(request-m["gap"])+"；若是新订单或新项目，请核实其用途预算，不能将差额认定为已证实需求。")
    if full:reasons.insert(0,"原借款需求在本次财务假设下通过压力及金额边界，但实际产品资格、利率和还款表仍待机构核验。")
    alternate=None
    if not full:
        alternate=dict(amount=debt,months=term,purpose=purpose,reduce_or_defer=max(0,request-debt),
            title="把借款缩到能承受的范围" if debt>0 else "暂缓新增借款，先处理现金和存量债务",
            explanation="建议本次仅申请"+money(debt)+"，剩余"+money(request-debt)+"通过缩小本次支出、分阶段实施或待落实非债务资金后再安排；没有把缺口假装补上。",
            composition=[dict(name=c["name"],amount=c["amount"],months=c["months"]) for c in plan["composition"] if c["amount"]>0])
    return dict(status="原需求通过财务筛选，新增用途需说明" if full and request>m["gap"]+.01 else "原需求通过本次财务筛选" if full else "原需求需要调整",
        reasonable=full,requested_amount=request,requested_months=term,purpose=purpose,historical_gap=m["gap"],
        annual_request_service_lower_bound=request_service,checks=checks,reasons=reasons,alternative=alternate)


def verify_sme_plan(plan):
    if not plan.get("available"):return dict(status="未验证",passed=False,checks=[],note="公开科目不足、矛盾或行业未覆盖。")
    rows=[];a=plan["algorithm"];f=plan["funding"];m=plan["model"]
    def check(label,value,limit):rows.append(dict(label=label,value=value,limit=limit,passed=value<=limit+max(.02,abs(limit)*1e-8)))
    total=sum(c["amount"] for c in plan["composition"])
    check("各渠道金额非负",-min(c["amount"] for c in plan["composition"]),0)
    check("明细与本金一致",abs(total-f["debt_total"]),.01)
    check("不超过用户外部借款需求",total,f["gap"])
    leverage=max(0,m["raw"]["total_assets"]*m["assumptions"]["max_leverage"]-m["raw"]["total_liabilities"])
    check("独立核对杠杆情景上限",total,leverage)
    peak=0.
    registered={c["id"]:c for c in match_sme_channels(m["raw"],plan["request_profile"])}
    for c in plan["composition"]:
        product=registered.get(c.get("catalog_id",c["id"]))
        allowed=bool(product and product["scope_match"] and product["source_current"] and product["min_months"]<=c["months"]<=product["max_months"] and c["months"]<=plan["request_profile"]["requested_months"] and c["repayment"]==product["repayment"])
        cap=min(f["gap"],product["maximum"] if product["maximum"] is not None else f["gap"]) if allowed else 0.
        check(c["name"]+"：独立核对官方产品与用途边界",c["amount"],cap)
        # Independent schedule expansion, no calls to peak_service_factor / LP factors.
        outstanding=c["amount"];schedule=[];monthly_rate=(c["rate"]+a["planning_stress"]["rate_up"])/12
        for month in range(c["months"]):
            principal=c["amount"]/c["months"] if c["repayment"]=="equal_principal" else c["amount"] if month==c["months"]-1 else 0.
            interest=outstanding*monthly_rate if c["repayment"]=="equal_principal" else c["amount"]*monthly_rate*c["months"] if month==c["months"]-1 else 0.
            schedule.append(principal+interest);outstanding=max(0,outstanding-principal)
        peak+=max((sum(schedule[i:i+12]) for i in range(len(schedule))),default=0.)
    check("独立还款表：全期限最重12个月新增本息",peak,a["service_budget"])
    stresscash=m["cash"]*(1-a["planning_stress"]["cash_drop"]) if m["cash"]>=0 else m["cash"]*(1+a["planning_stress"]["cash_drop"])
    check("现金能覆盖已有债务及新增还款峰值",a["target_dscr"]*(peak+m["service"]),stresscash)
    check("借款加待调整支出等于原需求",abs(total+f["unfunded_gap"]-f["need"]),.01)
    passed=all(c["passed"] for c in rows)
    return dict(status="通过财务与还款表验证 · 产品准入待核验" if passed else "仍有压力边界未通过，暂不建议执行",passed=passed,checks=rows,
        note="逐月展开还款表独立复算；未知还款方式按到期还本保守检查。财报不能证明产品资格，实际费用未计入，数学通过不能当作已获融资。")


def review_and_adjust(plan,data,profile):
    review=deepcopy(plan["request_review"])
    review["original_plan_verified"]=verify_sme_plan(plan)
    if review["reasonable"] is not False:return review
    candidates=[plan]
    for months in (12,24,36,60):
        if months<=profile.get("requested_months",24):continue
        # Working-capital facilities in this register never exceed three years.
        if months>36 and profile.get("requested_purpose")!="设备购置":continue
        candidates.append(build_sme_portfolio(data,{**profile,"requested_months":months},plan["algorithm"]["planning_stress"]))
    valid=[p for p in candidates if verify_sme_plan(p)["passed"]]
    if not valid:
        review["alternative"]={**(review["alternative"] or {}),"amount":0.,"months":profile.get("requested_months",24),"composition":[],
            "reduce_or_defer":profile["requested_amount"],"title":"暂缓新增借款，先处理现有现金缺口",
            "explanation":"即使不新增借款，现有债务也未通过现金压力线；本轮没有通过验证的债务替代方案。先缩减或延后支出、改善回款或协商存量还款，再重新测算。",
            "verified":False,"verification":review["original_plan_verified"]}
        return review
    chosen=min(valid,key=lambda p:(-p["funding"]["debt_total"],p["funding"]["total_assumed_interest"],max((c["months"] for c in p["composition"] if c["amount"]>0),default=0)))
    amount=chosen["funding"]["debt_total"]
    months=max((c["months"] for c in chosen["composition"] if c["amount"]>0),default=profile.get("requested_months",24))
    review["alternative"]=dict(amount=amount,months=months,purpose=profile.get("requested_purpose","经营周转"),
        reduce_or_defer=max(0,profile["requested_amount"]-amount),title="改为匹配用途的期限和借款金额",
        explanation="另行求解后，建议拟申请"+money(amount)+f"，最长{months}个月；比原需求少"+money(profile["requested_amount"]-amount)+"的支出先缩减或分阶段安排。延长期限可能增加总利息，银行仍须确认产品条件。",
        composition=[dict(name=c["name"],amount=c["amount"],months=c["months"]) for c in chosen["composition"] if c["amount"]>0],
        verified=True,verification=verify_sme_plan(chosen),portfolio=chosen)
    return review


def recommended_portfolio(outputs):
    from finbridge.market_rules import effective_portfolio
    plan=effective_portfolio(outputs)
    if plan and plan.get("engine")=="enterprise-v3":return plan
    review=outputs.get("review_financing_request") or {}
    alternative=review.get("alternative") or {}
    return alternative["portfolio"] if alternative.get("verified") and alternative.get("portfolio") else plan
