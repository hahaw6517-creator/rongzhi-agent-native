"""Reproducible enterprise decision models. LLMs never own numerical outputs.

Units inside the optimizer are ten thousand CNY. Binary variables activate
products; the Rockafellar-Uryasev epigraph minimizes CVaR of cash deficits.
"""
from copy import deepcopy
import hashlib
import json
import math
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from finbridge.public_finance import public_model

ENGINE = "enterprise-v3"
ALPHA = .95
SEED = 20261013
OPT_SAMPLES = 128
TEST_SAMPLES = 3000


def _money(v):
    return f"{v/1e8:,.6f}亿元"


def financial_analysis(raw, profile, metrics):
    """Tie every diagnosis to observed ratios and separately labelled forecasts."""
    m = public_model(raw, profile)
    a = m["assumptions"]
    findings = []
    def add(title, level, evidence, implication, action, keys):
        findings.append(dict(title=title, level=level, evidence=evidence,
                             implication=implication, action=action, metric_keys=keys))
    def value(key):
        return metrics.get(key, {}).get("value")
    ca, cl = raw.get("current_assets"), raw.get("current_liabilities")
    if ca is not None and cl and cl > 0:
        ratio = ca/cl
        add("短期周转", "关注" if ratio < 1 else "有缓冲", f"流动比率{ratio:.2f}倍，流动资产减流动负债为{_money(ca-cl)}。",
            "短期资产不足以覆盖短期负债，继续增加短债会加重到期压力。" if ratio < 1 else "账面短期资产有余量，但应收和存货不能直接当现金使用。",
            "把一年内到期债务与现金回收时间对齐，优先检查应收账款和库存占用。", ["current_ratio"])
    rev, profit, cfo = raw.get("revenue"), raw.get("net_profit"), raw.get("operating_cash_flow")
    if rev and profit is not None and cfo is not None:
        margin = profit/rev
        conversion = cfo/profit if profit > 0 else None
        add("利润兑现", "关注" if profit <= 0 or cfo < profit else "现金回收较好",
            f"净利率{margin:.1%}；经营现金流{_money(cfo)}，净利润{_money(profit)}。"+(f"每1元利润对应{conversion:.2f}元经营净现金。" if conversion is not None else "亏损时不使用现金利润比判断质量。"),
            "盈利尚未充分转成现金，借款能力不能只看利润。" if cfo < profit else "经营现金为偿债提供支持，还需扣除维持经营所需的投资。",
            "融资额度以现金预测和还款日程为准；若收入增长但回款变慢，应先改善账期。", ["net_margin", "cash_to_net_profit"])
    assets, liabilities = raw.get("total_assets"), raw.get("total_liabilities")
    if assets and liabilities is not None:
        leverage = liabilities/assets
        room = max(0, assets*a["max_leverage"]-liabilities)
        add("负债空间", "关注" if leverage >= a["max_leverage"] else "仍有模型空间",
            f"资产负债率{leverage:.1%}；按{a['max_leverage']:.0%}的情景上限，新增本金空间{_money(room)}。",
            "负债水平已达到模型边界，单纯提高借款需求不会提高可借金额。" if room <= 0 else "这一空间还要同时通过现金偿付约束，不能直接当授信额度。",
            "将杠杆空间与现金约束同时使用；超出部分考虑分期支出或权益资金。", ["debt_to_assets"])
    ar, inv = raw.get("accounts_receivable"), raw.get("inventory")
    if rev and ar is not None:
        prior = raw.get("beginning_accounts_receivable")
        days = ((ar+prior)/2 if prior is not None else ar)/rev*365
        improvement=min(10,days);release=rev/365*improvement
        add("回款占用", "需关注回款节奏", f"应收周转约{days:.1f}天（{'两期平均' if prior is not None else '期末余额代理'}）；回款提前{improvement:.1f}天对应约{_money(release)}的资金占用变化，非已实现回款。",
            "应收占用资金会推高周转融资需求；账面应收不等于符合保理条件的债权。",
            "优先催收高余额客户，评估10天账期改善情景；保理需确认合同、发票和债权无重复融资。", ["receivable_days"])
    if inv is not None and (raw.get("cost_of_goods_sold") or 0) > 0:
        old = raw.get("beginning_inventory")
        days = ((inv+old)/2 if old is not None else inv)/raw["cost_of_goods_sold"]*365
        add("存货占用", "需结合业务判断", f"存货周转约{days:.1f}天（{'两期平均' if old is not None else '期末余额代理'}）。",
            "库存占用越久，短期借款反复滚动的压力越大；不同行业的正常周转速度不同。",
            "结合采购周期压缩慢动库存，设备投资使用较长期限，避免用一年期资金承担多年回收项目。", ["inventory_days"])
    if rev and (raw.get("prior_revenue") or 0)>0:
        growth=rev/raw["prior_revenue"]-1
        oldcfo=raw.get("prior_operating_cash_flow")
        evidence=f"收入同比{growth:+.1%}。"
        if oldcfo is not None and cfo is not None:evidence+=f"经营现金较上期变化{_money(cfo-oldcfo)}。"
        add("增长与资金匹配", "关注增长质量", evidence,
            "收入增长如果依赖更长账期或备货，会占用更多现金；增长并不自动提高可偿债金额。",
            "结合回款与存货变化确认增长所需周转资金，现金预测不直接把收入增长率等同现金增长率。",["revenue_growth","cash_conversion_cycle"])
    if all(raw.get(k) is not None for k in ("net_profit","revenue","total_assets","ending_equity")) and rev>0 and raw["total_assets"]>0 and raw["ending_equity"]>0:
        avg_assets=(raw["total_assets"]+raw["beginning_total_assets"])/2 if raw.get("beginning_total_assets") is not None else raw["total_assets"]
        avg_equity=(raw["ending_equity"]+raw["beginning_equity"])/2 if raw.get("beginning_equity") is not None else raw["ending_equity"]
        if avg_assets>0 and avg_equity>0:
            add("盈利来源拆解", "杜邦分析",f"净利率{profit/rev:.1%} × 总资产周转{rev/avg_assets:.2f}倍 × 权益乘数{avg_assets/avg_equity:.2f}倍 = 权益回报{profit/avg_equity:.1%}（平均余额不齐时用期末代理）。",
                "股东回报可以来自利润率、资产效率或更高杠杆；依靠加债提高回报会同步增加偿付压力。",
                "优先改善利润与资产周转效率，再考虑加杠杆；平均权益非正时不使用这一分解。",["return_on_equity","total_asset_turnover"])
    if m["available"]:
        add("融资需求匹配", "需复核用途" if profile.get("requested_amount", 0) > m["gap"]*1.5+1 else "结合本次用途判断",
            f"按历史经营与投资外推的现金缺口{_money(m['gap'])}；本次外部需求{_money(profile.get('requested_amount',m['gap']))}。",
            "两者用途可能不同：历史缺口用于交叉检查，本次需求不是按历史缺口自动批准。",
            "明确新增项目和资金到账时间；最终建议由产品约束、现金偿付和风险共同决定。", [])
    if not m["available"]:
        return dict(available=False, findings=findings, forecast=None, missing=m["missing"], issues=m["issues"])
    annual_scope=profile.get('decision_scope')=='working-capital-12m'
    horizon = 12 if annual_scope else max(12, int(profile.get("requested_months",24)))
    # All future month values are scenario allocations, never uploaded observations.
    cf = m["cash"]/12
    existing = existing_schedule(raw, m, horizon)
    opening = raw["cash_equivalents_balance"]
    monthly = []
    balance = opening
    for t in range(horizon):
        balance += cf-existing[t]
        monthly.append(dict(month=t+1, operating=m["forecast_ocf"]/12,
            maintenance=m["capex"]*a["maintenance_share"]/12, available=cf,
            existing_service=float(existing[t]), balance=balance))
    volatility, vol_basis = .20, "仅有一至两期年报，无法估计月度波动；采用20%情景波动，非统计校准值。"
    prior = raw.get("prior_operating_cash_flow")
    if prior is not None and abs(prior) > 1:
        volatility = min(.50,max(.15,abs(raw["operating_cash_flow"]-prior)/abs(prior)))
        vol_basis = "以上下期经营现金流变化幅度设定波动，并截断在15%至50%；只有两点，仍是敏感性假设。"
    if raw.get('financial_history'):
        from finbridge.financial_history import annual_records
        observations=annual_records(raw)
        changes=[abs(c['values']['operating_cash_flow']-p['values']['operating_cash_flow'])/abs(p['values']['operating_cash_flow']) for p,c in zip(observations,observations[1:]) if c['year']==p['year']+1 and p['values'].get('operating_cash_flow') is not None and abs(p['values']['operating_cash_flow'])>1 and c['values'].get('operating_cash_flow') is not None]
        if len(changes)>=2:
            volatility=min(.5,max(.15,float(np.median(changes))))
            vol_basis='以可得连续年度经营现金变化绝对幅度的中位数作为敏感性参考，截断在15%至50%；年度变化不是月度波动估计，区间未作统计校准。'
    rng = np.random.default_rng(SEED+2)
    sims = np.tile(np.array([cf]*horizon),(1,1)) if annual_scope else scenario_cash(m, horizon, volatility, TEST_SAMPLES, rng)
    balances = opening+np.cumsum(sims-existing[None,:],axis=1)
    for t,row in enumerate(monthly):
        row.update(p10=float(np.quantile(balances[:,t],.1)),p90=float(np.quantile(balances[:,t],.9)))
    forecast = dict(months=monthly,horizon=horizon,volatility=volatility,volatility_basis=vol_basis,
        history_prediction=m.get('cash_prediction'),
        annual_cash=m["cash"],annual_operating=m["forecast_ocf"],opening_cash=opening,
        reserve=m["ledger"][next(i for i,r in enumerate(m["ledger"]) if r["key"]=="cash_reserve")]["value"],
        lowest_balance=min(r["balance"] for r in monthly),
        basis="年度经营现金情景减维持性投资后按月均分；保留正负号。已有短债在前12个月均分，长期借款36个月均分，利息随剩余本金测算。未识别真实季节性与合同日期。",
        band_note="年内现金均分只用于支付时点敏感性，不是月度预测。" if annual_scope else "P10—P90为模拟现金余额的中间80%范围；属于假设下的敏感性范围，不是预测准确率。",
        seed=SEED+2,simulations=TEST_SAMPLES)
    year_diagnosis=None
    if annual_scope:
        from finbridge.working_capital_year import annual_diagnosis
        year_diagnosis=annual_diagnosis(raw,m)
    return dict(available=True,findings=findings,forecast=forecast,diagnostics=m.get('diagnostics'),year_diagnosis=year_diagnosis,missing=[],issues=[],
        conclusion="先看利润是否收成现金，再看现金能覆盖多少还款；负债空间和资产数量只能作为上限，不能代替偿付能力。")


def existing_schedule(raw, model, horizon):
    """Explicit conservative proxy, including the previously ignored long debt."""
    principal = raw["short_term_debt"]+raw["current_portion_long_term_debt"]
    long = raw["long_term_debt"]
    rate = model["assumptions"]["assumed_rate"]
    historic = raw.get("interest_expense")
    result=[]
    for t in range(horizon):
        p = (principal/12 if t < 12 else 0)+(long/36 if t < 36 and model.get('scope')!='working-capital-12m' else 0)
        outstanding = max(0,principal*(1-t/12))+(long if model.get('scope')=='working-capital-12m' else max(0,long*(1-t/36)))
        interest = historic/12 if historic is not None and t < 36 else outstanding*rate/12
        result.append(p+interest)
    return np.asarray(result,dtype=float)


def scenario_cash(model, horizon, volatility, count, rng):
    # Correlated annual business shock + monthly noise; a negative base stays negative.
    common = rng.normal(0,volatility,(count,1))
    noise = rng.normal(0,volatility*.35,(count,horizon))
    annual = model["cash"]
    return annual/12 + abs(annual)/12*np.clip(common+noise,-1.5,1.5)


PRODUCTS = (
    dict(id="credit",name="流动资金信用贷款",max_months=12,spread=0.,fee=.003,repayment="按月付息，到期还本",purposes=("经营周转","订单备货","研发周转","综合融资"),basis="营业收入的15%，仅为模型筛选上限",condition="银行核验信用、经营记录及真实资金用途"),
    dict(id="secured",name="抵押经营贷款",max_months=60,spread=-.005,fee=.006,repayment="等额本金",purposes=("经营周转","订单备货","设备购置","研发周转","综合融资"),basis="固定资产账面池按假设比例折算，剔除租赁测算占用",condition="核验权属、可抵押性、现有抵押及评估值"),
    dict(id="factoring",name="应收账款保理",max_months=12,spread=.008,fee=.008,repayment="按月付息，到期还本",purposes=("经营周转","订单备货","综合融资"),basis="应收账款账面余额的60%，不是合格债权或获批额度",condition="核验真实交易、买方信用、账期及债权未转让；按有追索保理计债务"),
    dict(id="leasing",name="设备融资租赁",max_months=60,spread=.012,fee=.01,repayment="等额本金",purposes=("设备购置","综合融资"),basis="本次设备需求的80%，受历史长期资产购置现金及资产池约束",condition="确认租赁物与设备采购合同；款项定向支付，非自由现金"),
)


def product_rules(raw,profile,model):
    annual_scope=profile.get('decision_scope')=='working-capital-12m'
    purpose=profile.get("requested_purpose","经营周转")
    request=profile.get("requested_amount",model.get("gap",0))
    nca=max(0,(raw.get("total_assets") or 0)-(raw.get("current_assets") or 0))
    asset_pool=min(nca,raw['fixed_assets']) if raw.get('fixed_assets') is not None else nca
    # Equipment used for leasing cannot also back the secured facility.
    lease_pool=min(asset_pool,max(0,raw.get("capital_expenditure") or 0),request) if not annual_scope and purpose in {"设备购置","综合融资"} and profile.get("requested_months",24)>=12 else 0.
    rows=[]
    for p in PRODUCTS:
        a=model['assumptions']
        cap={"credit":max(0,raw.get("revenue") or 0)*a['credit_revenue_ratio'],
             "secured":max(0,asset_pool-lease_pool)*a['secured_advance_ratio'],
             "factoring":max(0,raw.get("accounts_receivable") or 0)*a['factoring_advance_ratio'],
             "leasing":lease_pool*a['leasing_advance_ratio']}[p["id"]]
        reason=None
        if not model["available"]:reason="财报尚未通过完整性与勾稽核验"
        elif purpose not in p["purposes"]:reason="与本次资金用途不匹配"
        elif p["id"]=="factoring" and raw.get("accounts_receivable") is None:reason="未提供报表应收账款，不能估算资产池"
        elif cap<=0:reason="报表未显示可用于该渠道测算的资产或经营规模"
        elif p["id"] in {"secured","leasing"} and profile.get("requested_months",24)<12:reason="本模型中长期渠道最短12个月"
        rate=max(.001,model["assumptions"]["assumed_rate"]+p["spread"])
        basis={'credit':f"营业收入×{a['credit_revenue_ratio']:.0%}的假设上限",'secured':f"{'固定资产账面池' if raw.get('fixed_assets') is not None else '旧数据非流动资产代理池'}剔除租赁占用后×{a['secured_advance_ratio']:.0%}",'factoring':f"应收账款账面余额×{a['factoring_advance_ratio']:.0%}",'leasing':f"固定资产、历史购置现金与本次需求共同限定设备池×{a['leasing_advance_ratio']:.0%}"}[p['id']]
        rows.append({**p,"basis":basis,"enabled":not reason,"status":"条件式候选" if not reason else "本次排除",
            "exclusion_reason":reason,"capacity":min(request,cap) if not reason else 0.,
            "rate":rate,"fee_rate":p["fee"],"fixed_fee":1000.,
            "months":min(int(profile.get("requested_months",24)),p["max_months"]),
            "conditions":[p["condition"]],"scope_match":not reason,"source_current":True,
            "evidence":[p["basis"]],"source":"内置通用产品规则，非金融机构报价", "url":""})
        if annual_scope:
            rows[-1]['rate']=a.get(p['id']+'_rate',rate)
            rows[-1]['fee_rate']=a.get(p['id']+'_fee_rate',p['fee'])
            rows[-1]['fixed_fee']=a.get(p['id']+'_fixed_fee',1000.)
            cap=min(cap,a.get(p['id']+'_limit',cap))
            rows[-1]['capacity']=min(cap,(request+1000)/(1-p['fee'])) if not reason else 0.
            rows[-1]['capacity']=min(cap,(request+rows[-1]['fixed_fee'])/(1-rows[-1]['fee_rate'])) if not reason else 0.
            if cap<=0:rows[-1].update(enabled=False,capacity=0.,status='本次排除',exclusion_reason='本次情景将渠道额度设为零')
            rows[-1]['months']=12
            rows[-1]['max_months']=rows[-1]['months']
            if p['id']=='secured':rows[-1].update(name='抵押流动资金贷款',repayment='按月付息，到期还本')
            if p['id']=='factoring':rows[-1].update(name='应收账款质押流动资金贷款',conditions=['核验真实债权、付款人信用、质押登记、账期与担保覆盖；不假设债权到期后自动替换或续贷'])
            if p['id']=='leasing':rows[-1].update(enabled=False,capacity=0.,exclusion_reason='一年期生产经营周转不配置设备租赁',status='本次排除')
    return rows


def unit_schedule(product, horizon, up=0.):
    n=product["months"];r=product["rate"]+up
    pay=np.zeros(horizon)
    for t in range(min(n,horizon)):
        pay[t]=((1/n)+(1-t/n)*r/12) if product["repayment"]=="等额本金" else r/12+(1. if t==n-1 else 0.)
    return pay


def _tail_mean(losses, alpha=ALPHA):
    """Fractionally weighted empirical upper tail: works with ties and small N."""
    values=np.sort(np.asarray(losses,dtype=float))[::-1]
    size=len(values)*(1-alpha);whole=int(math.floor(size));part=size-whole
    return float((sum(values[:whole])+(values[whole]*part if part>1e-10 else 0))/size)


def _solve(raw,profile,model,products,weight,planning_stress=None):
    a=model["assumptions"];request=profile.get("requested_amount",model.get("gap",0.))
    h=max(36,int(profile.get("requested_months",24)))
    # Extend to cover all existing debt even when the requested loan is short.
    rate_up=(planning_stress or {}).get("rate_up",a["rate_up"])
    drop=(planning_stress or {}).get("cash_drop",a["cash_drop"])
    schedules=np.asarray([unit_schedule(p,h) for p in products]).T
    stress_schedules=np.asarray([unit_schedule(p,h,rate_up) for p in products]).T
    existing=existing_schedule(raw,model,h)
    forecast=financial_analysis(raw,profile,{})["forecast"]
    vol=forecast["volatility"]
    sims=scenario_cash(model,h,vol,OPT_SAMPLES,np.random.default_rng(SEED))
    cash_cumulative=np.cumsum(sims,axis=1)/10000
    existing_cumulative=np.cumsum(existing)/10000
    schedule_cumulative=np.cumsum(schedules,axis=0)
    opening=raw["cash_equivalents_balance"]/10000
    reserve=forecast["reserve"]/10000
    # x[4], y[4], eta, z[S]. Loss=max_t(reserve - closing_cash_t, 0).
    nv=9+OPT_SAMPLES
    cap=np.array([p["capacity"]/10000 for p in products])
    fee=np.array([p["fee_rate"] for p in products]);fixed=np.array([p["fixed_fee"]/10000 for p in products])
    net=1-fee
    rows=[];lower=[];upper=[]
    def constraint(coeff,lo=-np.inf,hi=np.inf):
        rows.append(coeff);lower.append(lo);upper.append(hi)
    for i in range(4):
        row=np.zeros(nv);row[i]=1;row[4+i]=-cap[i];constraint(row,hi=0)
        row=np.zeros(nv);row[i]=-1;row[4+i]=min(cap[i],1.);constraint(row,hi=0)
    coverage=np.zeros(nv);coverage[:4]=net;coverage[4:8]=-fixed
    constraint(coverage,hi=request/10000)
    row=np.zeros(nv);row[:4]=1
    leverage=max(0,raw["total_assets"]*a["max_leverage"]-raw["total_liabilities"])/10000
    constraint(row,hi=leverage)
    cash=model["cash"]
    stressed=cash-abs(cash)*drop
    # All rolling windows, including year 2 and 3, not only the first year.
    for start in range(h):
        end=min(h,start+12);length=end-start
        budget=max(0,stressed/12*length/a["target_coverage"]-existing[start:end].sum())/10000
        row=np.zeros(nv);row[:4]=stress_schedules[start:end].sum(axis=0);constraint(row,hi=budget)
    for s in range(OPT_SAMPLES):
        for t in range(h):
            row=np.zeros(nv);row[:4]=schedule_cumulative[t];row[8]=-1;row[9+s]=-1
            constraint(row,hi=opening+cash_cumulative[s,t]-existing_cumulative[t]-reserve)
    integrality=np.zeros(nv);integrality[4:8]=1
    lb=np.zeros(nv);ub=np.full(nv,np.inf);ub[:4]=cap;ub[4:8]=1
    options=dict(time_limit=15,mip_rel_gap=1e-7)
    constraints=LinearConstraint(np.asarray(rows),np.asarray(lower),np.asarray(upper))
    first=milp(-coverage,integrality=integrality,bounds=Bounds(lb,ub),constraints=constraints,options=options)
    if not first.success:
        return dict(success=False,solver_status=int(first.status),message="未获得经证明最优的可行解；本次不发布金额方案。",amounts=[0.]*4,horizon=h)
    maxnet=float(coverage@first.x)
    constraint(coverage,lo=max(0,maxnet-1e-5))
    cost=np.zeros(nv);cost[:4]=schedules.sum(axis=0)-1+fee;cost[4:8]=fixed
    # Both objectives are measured in 10k CNY. Weight is monetary tail-risk aversion.
    objective=cost.copy();objective[8]=weight;objective[9:]=weight/((1-ALPHA)*OPT_SAMPLES)
    second=milp(objective,integrality=integrality,bounds=Bounds(lb,ub),
        constraints=LinearConstraint(np.asarray(rows),np.asarray(lower),np.asarray(upper)),options=options)
    if not second.success:
        return dict(success=False,solver_status=int(second.status),message="双目标求解未收敛，不用近似结果冒充最优。",amounts=[0.]*4,horizon=h)
    x=np.maximum(0,second.x[:4])*10000
    x[x<.01]=0
    fees=float(sum(x*fee)+sum(fixed[i]*10000 for i in range(4) if x[i]>0))
    losses=np.maximum(0,np.max(reserve-opening+existing_cumulative[None,:]+(schedule_cumulative@(x/10000))[None,:]-cash_cumulative,axis=1))*10000
    return dict(success=True,solver_status=int(second.status),amounts=x.tolist(),horizon=h,
        fees=fees,interest=float((schedules.sum(axis=0)-1)@x),net=float(x.sum()-fees),
        cvar=_tail_mean(losses),weight=weight,objective=float(second.fun*10000),
        mip_gap=float(second.mip_gap),max_net=maxnet*10000,opening=opening*10000,
        schedules=schedules,stress_schedules=stress_schedules,existing=existing,volatility=vol,
        eta=float(second.x[8]*10000),seed=SEED,optimisation_samples=OPT_SAMPLES)


def _assemble(raw,profile,model,products,sol,planning_stress=None):
    a=model["assumptions"];request=profile.get("requested_amount",model.get("gap",0.))
    drop=(planning_stress or {}).get("cash_drop",a["cash_drop"])
    up=(planning_stress or {}).get("rate_up",a["rate_up"])
    h=sol["horizon"];amounts=sol["amounts"]
    composition=[]
    for p,amount in zip(products,amounts):
        unit=unit_schedule(p,h)
        composition.append({**p,"amount":amount,"share":amount/max(1,sum(amounts)),
            "total_interest":amount*max(0,float(unit.sum())-1),
            "total_fee":amount*p["fee_rate"]+(p["fixed_fee"] if amount>0 else 0),
            "monthly_payment":amount*float(unit.max()),"capacity_input":"公开报表规则池",
            "reason":p["exclusion_reason"] or {
                "credit":"适用于本次短期经营用款，无需在模型中占用抵押资产；到期集中还本，必须有足够现金承接，不能假设自动续贷。",
                "secured":"账面资产池支持条件式抵押预算；较长期限等额归还本金可以分散还款压力，参考利率为假设，需机构确认抵押条件与评估值。",
                "factoring":"报表有应收账款，可评估将回款资产与周转融资匹配；本模型按有追索结构计入负债和到期还本，不能把转让与回款重复计入现金。",
                "leasing":"设备用途匹配租赁，按期分摊还款；额度对应设备池，款项定向支付，参考成本较高，作为抵押或现金约束下的补充。"}[p["id"]]})
    fees=sum(c["total_fee"] for c in composition);debt=sum(amounts);net=debt-fees
    scenarios=[]
    existing=existing_schedule(raw,model,h)
    for key,label,d,u in (("base","基准情景",0,0),("cash_drop","预计可用于偿债的现金下降",drop,0),("rate_up","利率上升",0,up),("double","现金下降且加息",drop,up),("cash_drop_30","现金下降30%",.3,0)):
        new=sum((unit_schedule(p,h,u)*x for p,x in zip(products,amounts)),np.zeros(h))
        totals=[float((existing+new)[i:min(h,i+12)].sum()) for i in range(max(1,h-11))]
        peak=max(totals);annual=model["cash"]-abs(model["cash"])*d
        idx=int(np.argmax(totals));newpeak=float(new[idx:idx+12].sum());oldpeak=float(existing[idx:idx+12].sum())
        scenarios.append(dict(id=key,label=label,cfads=annual,new_annual_service=newpeak,existing_annual_service=oldpeak,
            dscr=annual/peak if peak>0 else None,gap_to_target=max(0,a["target_coverage"]*peak-annual),cash_drop=d,rate_up=u,
            peak_start=idx+1,peak_end=min(h,idx+12)))
    f=dict(need=request,internal_used=0.,gap=request,debt_total=debt,unfunded_gap=max(0,request-net),fees_due=fees,
        fee_funding_gap=0.,total_unfunded_cash=max(0,request-net),net_proceeds=net,
        total_assumed_interest=sum(c["total_interest"] for c in composition),
        note="本次需求是外部净用款；手续费从融资中支付。本金、利息、费用分别列示；设备租赁为定向资金，不是可自由支取的银行存款。")
    return dict(engine=ENGINE,input_profile=deepcopy(profile),public_basis=True,available=bool(sol["success"]),status="条件式融资预算" if sol["success"] else sol["message"],
        funding=f,composition=composition,scenarios=scenarios,model=model,channel_catalog=products,
        algorithm=dict(name="MILP＋95% CVaR双目标优化",selection_objective="cost_cvar",objective=["先最大覆盖净资金需求","同等覆盖下平衡全期成本与尾部现金缺口"],
            target_dscr=a["target_coverage"],planning_stress=dict(cash_drop=drop,rate_up=up),
            service_budget=max(0,(model["cash"]-abs(model["cash"])*drop)/a["target_coverage"]-float(existing[:12].sum())),
            leverage_capacity=max(0,raw["total_assets"]*a["max_leverage"]-raw["total_liabilities"]),constraints=[dict(label='净到账不超过融资需求',sources=['requested_amount'],value=request),dict(label='新增本金的杠杆空间',sources=['total_assets','total_liabilities','max_leverage'],value=max(0,raw['total_assets']*a['max_leverage']-raw['total_liabilities'])),dict(label='滚动本息采用的年度压力现金',sources=['financial_history','cash_drop','maintenance_share'],value=model['cash']-abs(model['cash'])*drop),dict(label='诊断情景中较低的预计可用于偿债的现金',sources=['financial_history'],value=model.get('conservative_cash'))],
            diagnosis_basis=(model.get('diagnostics',{}).get('support') or {}).get('binding_scenario','一期现金代理与用户压力假设'),
            methods=['Rockafellar & Uryasev (2000)：CVaR线性化','报表现金收支恒等关系与全期限本息预算'],
            assumptions=["报价、可融资比例和费用为统一可调整的情景参数，不是实际授信或银行承诺。","以本金占用上限保守约束杠杆，不假设借款后资产同步膨胀。","既有负债还款日程采用报表余额代理，未知合同与季节性会影响结果。"],
            solver="SciPy / HiGHS",solver_status=sol["solver_status"],optimality_gap=sol.get("mip_gap"),
            risk_weight=sol.get("weight"),alpha=ALPHA,seed=SEED,samples=OPT_SAMPLES,
            loss_definition="全期限每条路径中低于经营现金留存线的最大缺口，融资款全部用于需求，不作为偿债现金重复计入。"),
        risk_flags=["公开账面资产池只用于条件式预算；实际可融资性及机构准入待核实。"],
        alternatives=[],recommendations=[],repayment_note="CFADS为预计可用于偿债的现金代理；DSCR为同一滚动12个月现金/本息，非合同认证值。", cvar=sol.get("cvar"))


def optimize_financing(raw,profile,planning_stress=None,selection_objective="cost"):
    if profile.get('decision_scope')=='working-capital-12m':
        from finbridge.working_capital_year import optimize_year
        return optimize_year(raw,profile,planning_stress)
    model=public_model(raw,profile)
    if not model["available"]:
        return dict(engine=ENGINE,available=False,status="财报数据未通过核验",model=model,
            funding=dict(need=profile.get("requested_amount",0),internal_used=0.,gap=profile.get("requested_amount",0),debt_total=0.,unfunded_gap=profile.get("requested_amount",0),fees_due=0.,total_assumed_interest=0.),
            composition=[],scenarios=[],algorithm=dict(name="MILP＋CVaR",target_dscr=1.2,planning_stress=dict(cash_drop=.2,rate_up=.01),constraints=[],assumptions=[]),risk_flags=model["issues"],alternatives=[])
    if model.get('conservative_cash') is not None and model['cash']>0:
        planning_stress=dict(planning_stress or {})
        planning_stress['cash_drop']=max(planning_stress.get('cash_drop',model['assumptions']['cash_drop']),1-model['conservative_cash']/model['cash'])
    products=product_rules(raw,profile,model)
    plans=[]
    for name,w in (("成本优先",0.),("均衡方案",.5),("风险优先",2.)):
        sol=_solve(raw,profile,model,products,w,planning_stress)
        plan=_assemble(raw,profile,model,products,sol,planning_stress)
        plan["strategy"]=name
        plans.append(plan)
    index=0 if selection_objective=="cost_only" else 2 if selection_objective=="repayment" else 1
    chosen=plans[index]
    chosen["frontier"]=[dict(title=p["strategy"],amount=p["funding"]["debt_total"],net=p["funding"].get("net_proceeds",0),
        gap=p["funding"]["unfunded_gap"],cost=p["funding"]["total_assumed_interest"]+p["funding"]["fees_due"],
        cvar=p.get("cvar"),amounts=[c["amount"] for c in p["composition"]],verified=verify_plan(p)["passed"]) for p in plans]
    chosen["frontier_note"]="三种权重均实际求解；如约束使结果相同，会如实显示，不伪造不同组合。"
    chosen["verification"]=verify_plan(chosen)
    chosen["risk_evaluation"]=evaluate_risk(chosen)
    chosen["decision_summary"]=decision_summary(chosen)
    return chosen


def verify_plan(plan):
    """Independent loan amortization and product/funding/rolling-window audit."""
    if not plan.get("available"):
        return dict(passed=False,status="数据或求解未通过",checks=[],note=plan.get("status",""))
    raw=plan["model"]["raw"];a=plan["model"]["assumptions"];annual_scope=plan.get('input_profile',{}).get('decision_scope')=='working-capital-12m';h=12 if annual_scope else max(36,max((c["months"] for c in plan["composition"]),default=36))
    checks=[]
    def check(label,passed,actual=None,limit=None):
        checks.append(dict(label=label,passed=bool(passed),actual=actual,limit=limit))
    reference=public_model(raw,plan['input_profile'])
    check('从财报重算基准现金',reference['available'] and abs(reference.get('cash',0)-plan['model']['cash'])<=.1,reference.get('cash'),plan['model']['cash'])
    if reference.get('conservative_cash') is not None:
        effective=plan['model']['cash']-abs(plan['model']['cash'])*plan['algorithm']['planning_stress']['cash_drop']
        check('未放松诊断保守现金边界',effective<=reference['conservative_cash']+.1,effective,reference['conservative_cash'])
    total=0.;fees=0.;interest=0.;monthly=np.zeros(h);base=np.zeros(h)
    rules={p["id"]:p for p in product_rules(raw,plan["input_profile"],plan["model"])}
    check("候选通道无重复或遗漏" if annual_scope else "四类产品无重复或遗漏",len(plan["composition"])==len(rules) and {c["id"] for c in plan["composition"]}==set(rules))
    check("净需求保持用户确认口径",abs(plan["funding"]["gap"]-plan["input_profile"]["requested_amount"])<=.01,plan["funding"]["gap"],plan["input_profile"]["requested_amount"])
    for c in plan["composition"]:
        amount=c["amount"];n=c["months"];remaining=amount
        expected=rules[c["id"]]
        check(c["name"]+"用途与资产池",amount<=expected["capacity"]+.1 and (amount<=.01 or expected["enabled"]),amount,expected["capacity"])
        check(c["name"]+"参数与规则一致",all(c[k]==expected[k] for k in ("rate","fee_rate","fixed_fee","months","repayment")))
        check(c["name"]+"最长产品期限",n<=c["max_months"],n,c["max_months"])
        for t in range(n):
            principal=amount/n if c["repayment"]=="等额本金" else amount if t==n-1 else 0
            cashinterest=remaining*c["rate"]/12
            base[t]+=principal+cashinterest
            monthly[t]+=principal+remaining*(c["rate"]+plan["algorithm"]["planning_stress"]["rate_up"])/12
            interest+=cashinterest;remaining=max(0,remaining-principal)
        check(c["name"]+"本金全期归还",remaining<=.01,remaining,0)
        fees+=amount*c["fee_rate"]+(c["fixed_fee"] if amount>.01 else 0);total+=amount
    f=plan["funding"]
    check("利息独立复算",abs(interest-f["total_assumed_interest"])<=.1,interest,f["total_assumed_interest"])
    check("费用独立复算",abs(fees-f["fees_due"])<=.1,fees,f["fees_due"])
    check("本金与渠道合计",abs(total-f["debt_total"])<=.1,total,f["debt_total"])
    check("净到账与需求闭合",abs(total-fees+f["unfunded_gap"]-f["gap"])<=.2,total-fees+f["unfunded_gap"],f["gap"])
    check("杠杆边界",raw["total_liabilities"]+total<=raw["total_assets"]*a["max_leverage"]+.2,
        raw["total_liabilities"]+total,raw["total_assets"]*a["max_leverage"])
    existing=existing_schedule(raw,plan["model"],h)
    drop=plan["algorithm"]["planning_stress"]["cash_drop"]
    stressed=plan["model"]["cash"]-abs(plan["model"]["cash"])*drop
    violation=float(a['target_coverage']*sum(existing+monthly)-stressed) if annual_scope else max((a["target_coverage"]*(existing[i:i+12]+monthly[i:i+12]).sum()-stressed/12*len(existing[i:i+12]) for i in range(h)),default=0)
    check("全期限滚动本息安全线",violation<=.2,float(violation),0)
    if annual_scope:
        ceiling=plan['annual_context']['operating_ceiling']
        check('一年经营用款上限',f['net_proceeds']<=ceiling+.2,f['net_proceeds'],ceiling)
        reserve=raw['cost_of_goods_sold']*a['reserve_days']/365
        minimum=min(raw['cash_equivalents_balance']-reserve+stressed*(t+1)/12-sum((existing+monthly)[:t+1]) for t in range(12))
        check('年内支付时点敏感性',minimum>=-.2,minimum,0)
        if plan['algorithm'].get('cvar_alpha') is not None:
            from finbridge.working_capital_year import evaluate_year
            recomputed=evaluate_year(plan)['cvar']
            check('情景CVaR独立复算',isinstance(plan.get('cvar'),(int,float)) and abs(recomputed-plan['cvar'])<=.2,recomputed,plan.get('cvar'))
    return dict(passed=all(c["passed"] for c in checks),status="通过独立数学验证" if all(c["passed"] for c in checks) else "存在未通过约束",
        checks=checks,note="验证复算金额和约束；不代表融资获批，也不能消除预测与合同代理误差。")


def evaluate_risk(plan):
    if plan.get('input_profile',{}).get('decision_scope')=='working-capital-12m':
        from finbridge.working_capital_year import evaluate_year
        return evaluate_year(plan)
    if not plan.get("available"):return dict(available=False)
    model=plan["model"];raw=model["raw"];a=model["assumptions"]
    h=max(36,max((c["months"] for c in plan["composition"]),default=36))
    x=[c["amount"] for c in plan["composition"]]
    existing=existing_schedule(raw,model,h)
    new=sum((unit_schedule(c,h)*amount for c,amount in zip(plan["composition"],x)),np.zeros(h))
    interest_shocks=np.clip(np.random.default_rng(SEED+101).normal(0,.005,(TEST_SAMPLES,1)),0,.03)
    floating=sum(((unit_schedule(c,h,1.)-unit_schedule(c,h))*amount for c,amount in zip(plan["composition"],x)),np.zeros(h))
    forecast=financial_analysis(raw,{**plan.get('input_profile',{}),**a,'requested_amount':plan['funding']['gap'],'requested_months':h},{})['forecast']
    sims=scenario_cash(model,h,forecast["volatility"],TEST_SAMPLES,np.random.default_rng(SEED+100))
    balances=raw["cash_equivalents_balance"]+np.cumsum(sims-existing-new-interest_shocks*floating[None,:],axis=1)
    minimum=balances.min(axis=1);loss=np.maximum(0,forecast["reserve"]-minimum)
    service=existing+new
    peak=max(float(service[i:i+12].sum()) for i in range(max(1,h-11)))
    cf=model["cash"]
    cash_boundary=1-a["target_coverage"]*peak/cf if cf>0 else None
    def passes_rate(up):
        payments=existing+sum((unit_schedule(c,h,up)*amount for c,amount in zip(plan["composition"],x)),np.zeros(h))
        return max(float(payments[i:i+12].sum()) for i in range(max(1,h-11)))*a["target_coverage"]<=cf+.01
    lo,hi=0.,.30
    if not passes_rate(0):rate_boundary=0.
    elif passes_rate(hi):rate_boundary=None
    else:
        for _ in range(40):
            mid=(lo+hi)/2
            if passes_rate(mid):lo=mid
            else:hi=mid
        rate_boundary=lo
    edges=np.histogram_bin_edges(minimum/10000,bins=14)
    if edges[0]<0<edges[-1]:edges=np.sort(np.unique(np.append(edges,0.)))
    histogram=np.histogram(minimum/10000,bins=edges)
    probability=float(np.mean(minimum<0))
    reserve_probability=float(np.mean(loss>0))
    exposure=plan["funding"]["debt_total"]
    shares=[v/exposure for v in x] if exposure>0 else []
    diagnostic_tests=[]
    for s in model.get('cash_scenarios',[]):
        ratio=s['debt_cash']/peak if peak>0 else None
        diagnostic_tests.append(dict(id=s['id'],label=s['label'],annual_cash=s['debt_cash'],cash_change=s['cash_change'],dscr=ratio,gap_to_target=max(0,a['target_coverage']*peak-s['debt_cash']),passed=s['debt_cash']>=a['target_coverage']*peak-.1,note='保持本次融资组合不变，检验利润和周转变化；未重新优化掩盖原方案风险。'))
    def wilson(probability,n):
        z=1.959963984540054;den=1+z*z/n
        center=(probability+z*z/(2*n))/den
        radius=z*math.sqrt(probability*(1-probability)/n+z*z/(4*n*n))/den
        return dict(lower=max(0,center-radius),upper=min(1,center+radius))
    stability=[dict(samples=n,cash_frequency=float(np.mean(minimum[:n]<0)),reserve_frequency=float(np.mean(loss[:n]>0)),cvar=_tail_mean(loss[:n])) for n in (1000,2000,TEST_SAMPLES)]
    dimensions=[dict(title='现金与经营留存',finding=f"{probability:.1%}的假设路径现金不足，{reserve_probability:.1%}跌破留存线。",action='保留经营现金；结合实际回款检查是否需要减少或延后用款。'),dict(title='还本付息与集中到期',finding=f"最重滚动12个月本息{_money(peak)}。",action='信用贷款和保理到期集中还本；先核对回收时间，不能默认续贷。'),dict(title='利润率与周转恶化',finding='已把历史不利利润率、回款和库存参数作用于当前组合。' if diagnostic_tests else '历史明细不足，暂未形成企业专属利润与周转情景。',action='优先核对现金减少最大的诊断情景，改善未落实前不作为新资金来源。'),dict(title='利率变化',finding='使用加息路径及逆向加息边界；假定全部新增融资重定价。',action='实际固定利率合同可降低敏感性，应取得报价后更新。'),dict(title='产品集中与期限',finding=f"产品份额集中度HHI为{sum(s*s for s in shares):.3f}。" if exposure>0 else '当前没有新增融资，集中度不作业务判断。',action='单一产品不自动等于高风险，重点检查机构依赖、到期集中和用途匹配。'),dict(title='模型与数据边界',finding='基于财报代理、历史情景和独立样本复算；没有违约训练标签或真实合同日程。',action='本结果不覆盖法律、交易对手违约、抵押权属与审批风险；这些条件仍须实际核实。')]
    return dict(available=True,samples=TEST_SAMPLES,seed=SEED+100,alpha=ALPHA,
        dimensions=dimensions,diagnostic_stress=diagnostic_tests,sample_stability=stability,frequency_sampling_range=wilson(probability,TEST_SAMPLES),sampling_note='95% Wilson范围仅描述给定模拟模型的抽样误差，不是企业真实违约率区间，也不证明现金预测准确。',theory='CVaR采用Rockafellar–Uryasev方法；情景、逆向压力及独立验证参考Basel (2018)压力测试原则。具体波动、利率冲击与安全线仍是显式假设。',
        cash_shortfall_probability=probability,reserve_breach_probability=reserve_probability,
        var=float(np.quantile(loss,ALPHA)),cvar=_tail_mean(loss),
        lowest_p10=float(np.quantile(minimum,.1)),lowest_median=float(np.median(minimum)),
        cash_decline_boundary=cash_boundary,rate_increase_boundary=rate_boundary,
        concentration_hhi=sum(s*s for s in shares),peak_service=peak,
        histogram=dict(edges=histogram[1].tolist(),counts=histogram[0].tolist()),
        conclusion=f"在{TEST_SAMPLES}条假设路径中，现金不足{int(np.sum(minimum<0))}条（{probability:.2%}），跌破经营现金留存线{int(np.sum(loss>0))}条（{reserve_probability:.2%}）。"+"这是情景频率，不是企业真实违约概率；未出现不代表现实风险为零。",
        reverse_summary=(f"预计可用于偿债的现金较基准下降约{max(0,cash_boundary):.1%}时会触及安全线。" if cash_boundary is not None and cash_boundary>=0 else "基准情景已达不到偿付安全线，应先处理现有还款压力。")+
            (f"利率额外上升约{rate_boundary*100:.2f}个百分点触及安全线。" if rate_boundary is not None else "利率上升30个百分点的搜索区间内尚未触线，不表示没有其他风险。"),
        assumptions=[forecast["volatility_basis"],"预计可用于偿债的现金使用共同业务冲击与月度噪声；加息冲击标准差0.5个百分点，截断0—3个百分点，假定全部新融资随之重定价。","采用与优化不同的随机样本检验，不能证明未采样情景绝对安全。","存量还款和现金流按月分配为代理；缺少合同和季节性，不能视为真实月度现金预算。"],
        actions=["保留经营现金储备，不把全部账面资金投入新项目。","按月比较实际回款与预测；低于安全线时降低新增支出或减少借款，并重新求解。","落实机构报价与合同后替换假设，复核费用和还款集中月份。"])


def annual_blockers(plan):
    """Explain failed checks with the same cash and schedules used by verification."""
    if not plan.get('annual_context') or not plan.get('model',{}).get('raw'):
        return []
    def cash_text(value):return f'{value/1e8:,.4f}亿元'
    model=plan['model'];raw=model['raw'];a=model['assumptions'];ctx=plan['annual_context']
    failed={x['label']:x for x in plan.get('verification',{}).get('checks',[]) if not x['passed']}
    blockers=[]
    if '全期限滚动本息安全线' in failed:
        existing=float(sum(existing_schedule(raw,model,12)))
        required=a['target_coverage']*existing
        worst=min(ctx['scenarios'],key=lambda s:s['annual_cash'])
        cash=ctx['stress_cash']
        blockers.append(dict(title='现有还款已超过压力现金承受范围',
            evidence=f"{worst['label']}下预计可用于偿债的现金为{cash_text(cash)}；模型估算已有债务一年本息{cash_text(existing)}，按{a['target_coverage']:.2f}倍安全线需{cash_text(required)}，即使不新增借款也差{cash_text(max(0,required-cash))}。",
            action='先核对现有债务的实际到期本金、利息及已落实的再融资，再复核压力假设；仅换融资渠道或降低申请额不能解除这项限制。'))
    if '年内支付时点敏感性' in failed:
        reserve=raw['cost_of_goods_sold']*a['reserve_days']/365
        opening=raw['cash_equivalents_balance']
        deficit=max(0,-failed['年内支付时点敏感性']['actual'])
        blockers.append(dict(title='年内现金无法保持设定留存线',
            evidence=f"期末现金{cash_text(opening)}；按{a['reserve_days']:g}天营业成本设定的现金留存线为{cash_text(reserve)}。按年度现金和已有本息均匀分配，全年最紧时点距留存线差{cash_text(deficit)}。",
            action='核对实际现金收付节奏与必要经营支出；营业成本含非现金费用，当前留存线是敏感性假设，不是企业真实最低现金。'))
    if '杠杆边界' in failed:
        blockers.append(dict(title='负债超过设定上限',evidence=f"方案后负债{cash_text(failed['杠杆边界']['actual'])}，模型上限{cash_text(failed['杠杆边界']['limit'])}。",action='先减少债务或补充权益资金，再评估新增融资。'))
    if not blockers and plan['funding']['debt_total']<=.01:
        channels=[c for c in plan['composition'] if c['id']!='leasing']
        excluded=[c for c in channels if not c.get('enabled') or c.get('capacity',0)<=0]
        if len(excluded)==len(channels):
            blockers.append(dict(title='没有可进入求解的融资渠道',evidence='；'.join(c['name']+'：'+(c.get('exclusion_reason') or '规则测算容量为零') for c in excluded),action='检查资产余额、用途及手动额度限制；账面资产不等于已获批授信。'))
        else:
            blockers.append(dict(title='本轮未得到可发布的新增融资结果',evidence='未通过检查：'+'、'.join(failed) if failed else '求解未形成正的净融资额，不能把零值当作银行授信结论。',action='查看求解状态和验证记录，核对参数后重新测算。'))
    return blockers


def decision_summary(plan):
    f=plan["funding"];v=plan.get("verification",{})
    selected=[c for c in plan.get("composition",[]) if c["amount"]>.01]
    if not plan.get("available"):return dict(title="先补齐或修正财报",text=plan["status"],actions=["查看企业与数据中的缺失和核验问题。"])
    blockers=annual_blockers(plan)
    if blockers:
        title='本次融资未通过：'+blockers[0]['title']
        text=' '.join(x['evidence']+' '+x['action'] for x in blockers)
    elif f["debt_total"]<=.01:
        title="当前条件不支持新增债务"
        failed=[x for x in v.get("checks",[]) if not x["passed"]]
        text="产品用途、资产池或现有还款压力限制了融资空间；提高申请金额不会解除这些约束。"
        if failed:text+="独立复算发现："+"、".join(x["label"] for x in failed)+"未通过，需先改善现金或调整现有还款。"
    elif f["unfunded_gap"]>1:
        title="建议分阶段融资"
        text=f"本次需要净资金{_money(f['gap'])}，组合本金{_money(f['debt_total'])}扣除费用后提供{_money(f['net_proceeds'])}；剩余{_money(f['unfunded_gap'])}先延后或调整支出。"
    else:
        title="本次需求可形成条件式组合"
        text=f"组合本金{_money(f['debt_total'])}扣除费用{_money(f['fees_due'])}后可覆盖本次净用款；全期利息{_money(f['total_assumed_interest'])}。"
    return dict(title=title,text=text,verified=v.get("passed",False),blockers=blockers,
        rationale=[c["name"]+"："+c["reason"] for c in selected],
        actions=[x['action'] for x in blockers] if blockers else ["先确认拟申请渠道的资产与用途条件，按实际报价复算。", "保持本次还款安全余量；尚未覆盖的需求不能计作已落实资金。"])


def review_request(plan, raw, profile):
    v=verify_plan(plan);f=plan["funding"]
    short=max(0,f["unfunded_gap"])
    alternative=None
    if short>.5 and f["debt_total"]>.1 and v["passed"]:
        # Re-solve reduced NET demand; rounding principal into a demand would overborrow fees.
        amount=max(0,f.get("net_proceeds",0))
        replacement=optimize_financing(raw,{**profile,"requested_amount":amount}) if amount>.1 else None
        if replacement and replacement["verification"]["passed"]:
            alternative=dict(amount=amount,months=profile.get("requested_months",24),purpose=profile.get("requested_purpose","经营周转"),
                title="缩减或分阶段安排本次用款",explanation=f"净用款需求调整为{_money(amount)}，原需求中的{_money(short)}先延后。已按调整后的净需求重新求解。",
                verified=True,verification=replacement["verification"],portfolio=replacement,reduce_or_defer=short)
    return dict(status="原需求可覆盖" if short<=.1 and v["passed"] else "原需求需要调整",reasonable=short<=.1 and v["passed"],
        original_plan_verified=v,alternative=alternative,
        explanation=plan.get("decision_summary",{}).get("text",plan["status"]),
        requested_amount=f["gap"],shortfall=short)
