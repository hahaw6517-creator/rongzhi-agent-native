"""Auditable public-data models; estimates and scenario settings never become facts."""
from copy import deepcopy
import math
from numbers import Real
from finbridge.public_data import public_only, PUBLIC_LABELS, SCHEMA

DEFAULTS = dict(reserve_days=45., capex_multiplier=1., maintenance_share=.2, max_leverage=.65,
    target_coverage=1.2, assumed_rate=.055, cash_drop=.2, rate_up=.01,credit_revenue_ratio=.15,secured_advance_ratio=.4,factoring_advance_ratio=.6,leasing_advance_ratio=.8)
LIMITS = dict(reserve_days=(0,180),capex_multiplier=(0,3),maintenance_share=(0,1),max_leverage=(.1,.9),
    target_coverage=(1.,2.),assumed_rate=(0,.3),cash_drop=(.2,.4),rate_up=(.01,.05),forecast_growth=(-.3,.5),credit_revenue_ratio=(0,1),secured_advance_ratio=(0,1),factoring_advance_ratio=(0,1),leasing_advance_ratio=(0,1))
LIMITS.update(cvar_alpha=(.5,.99),cvar_weight=(0,10),calibration_share=(0,1),calibration_limit=(0,1),receivable_delay_days=(0,180),margin_drop=(0,.3))
for _product in ('credit','secured','factoring'):
    LIMITS.update({f'{_product}_rate':(0,.3),f'{_product}_fee_rate':(0,.3),f'{_product}_fixed_fee':(0,1e7),f'{_product}_limit':(0,1e10)})
REQUEST_KEYS = {"requested_amount", "requested_months", "requested_purpose", "enterprise_type", "decision_engine", "optimization_strategy", "decision_scope"}
PURPOSES = ("经营周转", "订单备货", "设备购置", "研发周转", "综合融资")
ENTERPRISE_TYPES = ("一般企业", "中小微企业", "科创企业")


def validate_request(settings):
    if settings.get('decision_scope')=='working-capital-12m' and (settings.get('requested_months',12)!=12 or settings.get('requested_purpose','经营周转')!='经营周转'):
        raise ValueError('当前仅支持12个月生产经营周转；可调整金额和情景参数，不能改变期限或用途。')
    if settings.get('decision_scope') not in (None,'working-capital-12m'):raise ValueError('不支持的分析范围')
    amount=settings.get("requested_amount");months=settings.get("requested_months",24)
    if amount is not None and (isinstance(amount,bool) or not isinstance(amount,Real) or not math.isfinite(amount) or not 0<amount<=1e10):
        raise ValueError("请填写大于0且不超过100亿元的外部借款需求（元）")
    if isinstance(months,bool) or not isinstance(months,Real) or not math.isfinite(months) or not 1<=months<=60 or int(months)!=months:
        raise ValueError("融资期限须为1至60的整数个月")
    if settings.get("requested_purpose","经营周转") not in PURPOSES:
        raise ValueError("请选择支持的资金用途")
    if settings.get("decision_engine") not in (None,"enterprise-v3"):
        raise ValueError("不支持的决策引擎")
    if settings.get('optimization_strategy','balanced') not in {'balanced','cost_only','repayment'}:raise ValueError('不支持的优化策略')
    if settings.get("enterprise_type","一般企业") not in ENTERPRISE_TYPES:
        raise ValueError("企业类型参数无效")
NEEDED = ("total_assets","total_liabilities","current_assets","current_liabilities","cash_equivalents_balance",
    "revenue","cost_of_goods_sold","net_profit","operating_cash_flow","capital_expenditure",
    "short_term_debt","long_term_debt","current_portion_long_term_debt")


def public_profile(data,previous=None):
    previous=previous or {}
    validate_request(previous)
    return {**DEFAULTS,**{k:v for k,v in previous.items() if k in LIMITS and v is not None},
        **{k:v for k,v in previous.items() if k in REQUEST_KEYS and v is not None},
        "analysis_mode":"public-v2","industry":data.get("industry", "未披露"),"region":data.get("region", "未披露"),
        "objective":previous.get("objective", "分析财务状况与融资需求，平衡融资成本和现金风险，并验证方案。")}


def public_model(raw, settings=None):
    data=public_only(raw);settings=settings or {}
    validate_request(settings)
    assumptions={**DEFAULTS,**{k:settings[k] for k in LIMITS if settings.get(k) is not None}}
    for key,value in assumptions.items():
        lo,hi=LIMITS[key]
        if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError("情景假设超出范围："+key)
    missing=[k for k in NEEDED if data.get(k) is None]
    invalid=[];issues=[];ledger=[]
    quality=None
    if data.get('input_contract')=='annual-v3' or settings.get('decision_scope')=='working-capital-12m':
        from finbridge.data_contract import completeness
        quality=completeness(data)
        if not quality['complete']:issues.append(quality['message'])
    from finbridge.public_data import BLOCKS
    signed={k for rows in BLOCKS.values() for key,_,prior,negative in rows if negative for k in (key,prior) if k}
    for key,value in data.items():
        if key in PUBLIC_LABELS and value is not None and (isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value) or abs(value)>1e15 or value<0 and key not in signed):
            invalid.append(key)
    if invalid:
        missing=list(dict.fromkeys(missing+invalid))
    def record(key,label,value,formula,sources,kind="模型估算"):
        ledger.append(dict(key=key,label=label,value=value,formula=formula,sources=sources,kind=kind))
        return value
    assets,liabs=data.get("total_assets"),data.get("total_liabilities")
    if not invalid:
        from finbridge.deep_diagnostics import historical_issues
        issues.extend(historical_issues(data,cash_sensitivity=settings.get('_temporary_financial_sensitivity') is True))
        loans=("short_term_debt","long_term_debt","current_portion_long_term_debt")
        if liabs is not None and all(data.get(k) is not None for k in loans) and sum(data[k] for k in loans)>liabs+max(1.,abs(liabs)*1e-5):
            issues.append("短期借款、长期借款及一年内到期非流动负债合计超过负债合计，请核对重复填报")
        if assets is not None and data.get("current_assets") is not None and data["current_assets"]>assets:
            issues.append("流动资产超过资产总计")
        if liabs is not None and data.get("current_liabilities") is not None and data["current_liabilities"]>liabs:
            issues.append("流动负债超过负债合计")
        if all(data.get(k) is not None for k in ("total_assets","total_liabilities","ending_equity")) and abs(assets-liabs-data["ending_equity"])>max(1.,abs(assets)*1e-5):
            issues.append("资产不等于负债加权益，请核对合并口径和单位")
        asset_parts=("cash_and_equivalents","accounts_receivable","inventory","prepayments")
        if data.get("current_assets") is not None and all(data.get(k) is not None for k in asset_parts) and sum(data[k] for k in asset_parts)>data["current_assets"]+max(1.,abs(data["current_assets"])*1e-5):
            issues.append("货币资金、应收、存货与预付款合计超过流动资产，请核对重复科目或单位")
        if data.get("current_liabilities") is not None and data.get("short_term_debt") is not None and data.get("current_portion_long_term_debt") is not None and data["short_term_debt"]+data["current_portion_long_term_debt"]>data["current_liabilities"]+max(1.,abs(data["current_liabilities"])*1e-5):
            issues.append("短期借款与一年内到期非流动负债合计超过流动负债")
        # Cash equivalents may include investments outside the balance-sheet cash line.
        # Do not reject a legitimate disclosure merely because these balances differ.
    period=str(data.get("report_period", ""))
    import re
    period_known=bool(re.fullmatch(r"20\d{2}(?:年度|年|-12-31)?",period))
    if not period_known:
        issues.append("当前模型要求完整年度报表；不能将季度数据直接当全年")
    if any(word in str(data.get("industry","")) for word in ("银行","保险","证券","金融")):
        issues.append("当前现金周转模型适用于非金融企业，金融机构需要专门的资本充足与流动性模型")
    growth=assumptions.get("forecast_growth")
    if growth is None:
        growth=(data["revenue"]/data["prior_revenue"]-1 if isinstance(data.get("revenue"),Real) and isinstance(data.get("prior_revenue"),Real) and data["prior_revenue"]>0 else 0.)
        growth=max(-.3,min(.5,growth));assumptions["forecast_growth"]=growth
        growth_basis="上期收入同比截断到-30%至50%的情景外推；无上期收入时使用0%平稳情景，不是增长预测"
    else:
        growth_basis="用户调整的情景增长率，不是企业内部预测"
    record("growth","收入增长情景",growth,growth_basis,["revenue","prior_revenue"],"情景假设")
    required_wc=("accounts_receivable","inventory","prepayments","accounts_payable","advance_receipts","contract_liabilities")
    prior_wc=("beginning_accounts_receivable","beginning_inventory","beginning_prepayments","beginning_accounts_payable","beginning_advance_receipts","prior_contract_liabilities")
    wc_ok=all(isinstance(data.get(k),Real) and k not in invalid for k in required_wc+prior_wc)
    request_mode=settings.get("requested_amount") is not None
    if not wc_ok and not request_mode:
        missing=list(dict.fromkeys(missing+[k for k in required_wc+prior_wc if data.get(k) is None]))
    ready=not(missing or issues or invalid)
    model=dict(available=ready,missing=missing,issues=issues,invalid=invalid,period_known=period_known,data_quality=quality,
        scope=settings.get('decision_scope'),
        assumptions=assumptions,ledger=ledger,raw=data,
        note="原始数据仅来自公开报表。融资需求、现金储备、维持性开支与到期本息均为可复算情景估算；不代表企业内部预算、真实授信或准确还款计划。")
    if settings.get('_temporary_financial_sensitivity') is True:model['note']+='本次为单变量财务敏感性，未构造完整平衡报表；不可作为真实财报采用。'
    if not ready:
        return model
    if not wc_ok:
        # A declared funding request can be screened without inventing missing working-capital balances.
        record("working_capital_unavailable","营运资本细分测算暂缺",None,"两期营运资本科目未齐：不补零；本次以最近完整年度经营现金流作平稳情景",list(required_wc+prior_wc),"数据缺口")
        wc=dwc=nextwc=None
        ocf=record("forecast_ocf","下一年度经营净现金情景",data["operating_cash_flow"],"最近完整年度经营现金流保持不变；未使用缺失科目或增长外推",["operating_cash_flow"])
    else:
        wc=record("operating_nwc","经营性净营运资本",sum(data[k] for k in required_wc[:3])-sum(data[k] for k in required_wc[3:]),
        "应收账款＋存货＋预付款项－应付账款－预收款项－合同负债",list(required_wc),"报表计算")
        oldwc=sum(data[k] for k in prior_wc[:3])-sum(data[k] for k in prior_wc[3:])
        dwc=record("historical_nwc_change","历史经营性营运资本变化",wc-oldwc,"本期经营性净营运资本－上期同口径值",list(required_wc+prior_wc),"报表计算")
        nextwc=record("growth_cash_need","增长占用现金",wc*growth,"本期经营性净营运资本×收入增长情景（负值为释放现金）",list(required_wc)+["forecast_growth"])
        prewc=record("cash_before_wc","营运资本变动前现金代理",data["operating_cash_flow"]+dwc,"经营现金流＋历史经营性营运资本增加额",["operating_cash_flow","historical_nwc_change"])
        ocf=record("forecast_ocf","下一年度经营净现金情景",prewc*(1+growth)-nextwc,"营运资本变动前现金代理×(1＋增长情景)－增长占用现金",["cash_before_wc","forecast_growth","growth_cash_need"])
    from finbridge.deep_diagnostics import build_diagnostics
    diagnostics=build_diagnostics(data,growth)
    support=diagnostics['support']
    if support:
        ocf=support['base_ocf']
        for row in ledger:
            if row['key']=='forecast_ocf':row.update(value=ocf,formula=support['formula'])
    model['diagnostics']=diagnostics
    from finbridge.cash_forecast import cash_forecast
    cash_prediction=cash_forecast(data,settings.get('forecast_growth'),calibrate=settings.get('decision_scope')=='working-capital-12m',calibration_share=assumptions.get('calibration_share',.5),calibration_limit=assumptions.get('calibration_limit',.3))
    model['cash_prediction']=cash_prediction
    if cash_prediction['future']:
        prediction=cash_prediction['future'];ocf=prediction['annual_operating']
        for row in ledger:
            if row['key']=='forecast_ocf':row.update(value=ocf,formula=prediction['formula']+('；加上历史误差校正额' if settings.get('decision_scope')=='working-capital-12m' else ''),sources=['financial_history','forecast_growth'])
    if support:
        support['financing_base_ocf']=ocf
        support['financing_conservative_ocf']=min(ocf,support['conservative_ocf'])
    capex=record("planned_capex","资本开支情景",data["capital_expenditure"]*assumptions["capex_multiplier"],"公开历史购建长期资产现金×资本开支倍数",["capital_expenditure","capex_multiplier"])
    reserve=record("cash_reserve","经营现金留存情景",data["cost_of_goods_sold"]*assumptions["reserve_days"]/365,"营业成本÷365×留存天数；不是企业已确认最低现金",["cost_of_goods_sold","reserve_days"])
    freecash=record("available_cash_proxy","历史现金可投入代理",max(0,data["cash_equivalents_balance"]-reserve),"max(0,公开现金及现金等价物－现金留存情景)",["cash_equivalents_balance","cash_reserve"])
    principal=record("maturity_proxy","一年内本金到期压力代理",data["short_term_debt"]+data["current_portion_long_term_debt"],"短期借款＋一年内到期非流动负债；只是余额压力代理，不是真实合同日程",["short_term_debt","current_portion_long_term_debt"])
    interest=data.get("interest_expense")
    if interest is None:
        interest=assumptions["assumed_rate"]*sum(data[k] for k in ("short_term_debt","long_term_debt","current_portion_long_term_debt"))
        interest_basis="利息未公开：借款及一年内到期负债余额×情景利率，不当作实际费用"
    else:
        interest_basis="公开历史利息费用外推，不是未来已签约利息"
    service=record("existing_service_proxy","已有债务年度本息压力代理",principal+interest,"本金到期压力代理＋利息压力代理；"+interest_basis,["maturity_proxy","interest_expense","assumed_rate"])
    cash=record("debt_cash_proxy","年度还款现金代理",ocf-capex*assumptions["maintenance_share"],"下一年度经营净现金情景－资本开支情景×维持性占比",["forecast_ocf","planned_capex","maintenance_share"])
    if support:
        model['conservative_cash']=record('historical_conservative_cash','诊断情景保守还款现金',min(ocf,support['conservative_ocf'])-capex*assumptions['maintenance_share'],'两年现金预测与利润周转情景取较低经营现金，再扣除维持性投资',['financial_history','maintenance_share'])
        model['cash_scenarios']=[{**s,'debt_cash':s['ocf']-capex*assumptions['maintenance_share']} for s in support['scenarios']]
    # Historical CFO is normally before financing-classified interest in Chinese CFS.
    annual_scope=settings.get('decision_scope')=='working-capital-12m'
    need=record("cash_uses","年度现金用途情景",capex*assumptions['maintenance_share']+service+max(0,-ocf) if annual_scope else capex+service+max(0,-ocf),"维持性投资＋已有本息压力代理＋经营现金赤字；不把设备扩张预算计为周转融资需求" if annual_scope else "资本开支＋已有本息压力代理＋经营现金赤字",["planned_capex","existing_service_proxy","forecast_ocf"])
    own=record("cash_sources","非新增融资现金来源情景",max(0,ocf)+freecash,"正经营净现金情景＋历史现金可投入代理",["forecast_ocf","available_cash_proxy"])
    gap=record("financing_need","自主推导融资缺口",max(0,need-own),"max(0,现金用途情景－非新增融资现金来源情景)",["cash_uses","cash_sources"])
    model.update(wc=wc,forecast_ocf=ocf,capex=capex,freecash=freecash,service=service,cash=cash,
        need=need,internal=min(need,own),gap=gap,working_gap=min(gap,max(0,gap-capex)),equipment_gap=min(gap,capex),
        interest=interest,principal=principal)
    return model


def prepare_public(raw, settings=None):
    model=public_model(raw,settings);data=deepcopy(model["raw"])
    for src,dst in (("accounts_receivable","ending_accounts_receivable"),("inventory","ending_inventory"),("accounts_payable","ending_accounts_payable"),("total_assets","ending_total_assets")):
        data[dst]=data.get(src)
    if all(data.get(k) is not None for k in ("current_assets","inventory","prepayments")):
        data["quick_assets"]=data["current_assets"]-data["inventory"]-data["prepayments"]
    if all(data.get(k) is not None for k in ("depreciation_expense","amortization_expense")):
        data["depreciation_amortization"]=data["depreciation_expense"]+data["amortization_expense"]
    request=(settings or {}).get("requested_amount")
    profile={**(settings or {}),**model["assumptions"],"analysis_mode":SCHEMA,"amount":request if request is not None else model.get("need",0.),"internal_funds":0. if request is not None else model.get("internal",0.),
        "months":(settings or {}).get("requested_months",24) if request is not None else 36,"purpose":(settings or {}).get("requested_purpose","经营周转") if request is not None else "综合融资","industry":data.get("industry") or "未披露","region":data.get("region") or "未披露"}
    if model["available"]:
        data.update(cash_flow_available_for_debt_service=model["cash"],scheduled_debt_service=model["service"],
            financing_need=model["need"],available_internal_funds=model["internal"])
    return data,profile,model
