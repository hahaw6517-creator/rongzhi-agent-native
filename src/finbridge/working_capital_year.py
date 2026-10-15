"""One-year operating finance: explicit scenarios, one cost-optimal portfolio."""
import math
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from finbridge.financial_history import annual_records

SCOPE='working-capital-12m'
CVAR_ALPHA=.8
CVAR_WEIGHT=.1

def tail_cash_pressure(tests,base_cash,alpha=CVAR_ALPHA):
    """Erosion of post-service cash margin, not probability of default."""
    from finbridge.enterprise_model import _tail_mean
    base=next(s for s in tests if s['id']=='base')
    losses=[max(0,base_cash-s['annual_cash']+s['total_service']-base['total_service']) for s in tests]
    return losses,_tail_mean(losses,alpha)


def cvar_explanation(tests,alpha):
    """Trace the equal-weight tail mean to cash changes and debt-service changes."""
    base=next(s for s in tests if s['id']=='base')
    weight=1/len(tests);remaining=1-alpha;rows=[]
    for s in sorted(tests,key=lambda s:s['tail_cash_pressure'],reverse=True):
        included=min(weight,max(0,remaining));remaining=max(0,remaining-included)
        if included<=1e-12:continue
        share=included/(1-alpha)
        rows.append(dict(id=s['id'],label=s['label'],annual_cash=s['annual_cash'],
            cash_decline=base['annual_cash']-s['annual_cash'],
            service_increase=s['total_service']-base['total_service'],
            loss=s['tail_cash_pressure'],scenario_weight=weight,included_weight=included,
            tail_share=share,contribution=share*s['tail_cash_pressure']))
    return dict(base_cash=base['annual_cash'],base_service=base['total_service'],
        base_margin=base['annual_cash']-base['total_service'],tail_weight=1-alpha,rows=rows,
        max_safety_gap=max(s['gap_to_target'] for s in tests),
        meaning='所设较差情景中，企业偿债后现金余量相对基准的平均下降；含经营现金变化和偿债支出变化，不是贷款本金损失。',
        usage='用于比较同一企业、相同情景与权重下不同方案的现金余量抗压表现；是否还得上债另看本息覆盖倍数及安全线缺口。',
        limitations='情景等权和置信水平是建模假设，不是真实发生概率；金额受企业规模影响，不宜直接跨企业比较。')

def year_profile(profile=None):
    prior=profile or {};rate=prior.get('assumed_rate',.04) if prior.get('decision_scope')==SCOPE else .04
    return {**prior,'assumed_rate':rate,'decision_scope':SCOPE,'decision_engine':'enterprise-v3','requested_months':12,'requested_purpose':'经营周转','optimization_strategy':'cost_only'}

def annual_scenarios(raw,model,planning_stress=None):
    rows=annual_records(raw);v=rows[-1]['values'];a=model['assumptions'];f=model.get('cash_prediction',{}).get('future') or {}
    revenue=f.get('projected_revenue',v['revenue']);cost=revenue*v['cost_of_goods_sold']/v['revenue']
    dso=[r['values']['accounts_receivable']/r['values']['revenue']*365 for r in rows if r['values'].get('revenue',0)>0 and r['values'].get('accounts_receivable') is not None]
    margins=[1-r['values']['cost_of_goods_sold']/r['values']['revenue'] for r in rows if r['values'].get('revenue',0)>0 and r['values'].get('cost_of_goods_sold') is not None]
    delay=max(5.,min(30.,max(dso)-dso[-1])) if dso else 5.
    margin_drop=max(.01,min(.05,max(margins)-min(margins))) if margins else .01
    delay=a.get('receivable_delay_days',delay);margin_drop=a.get('margin_drop',margin_drop)
    cash=model['cash'];drop=max(a['cash_drop'],(planning_stress or {}).get('cash_drop',0));up=max(a['rate_up'],(planning_stress or {}).get('rate_up',0))
    def item(key,label,amount,rate,rule,origin):
        return dict(id=key,label=label,annual_cash=amount,rate_up=rate,rule=rule,parameter_origin=origin,cash_change=amount-cash)
    scenarios=[item('base','基准：误差校正后现金',cash,0,'下一年校正经营现金减维持性投资；不重复扣除已包含的历史周转变化。','三年财报与一次历史误差检验'),
        item('cash','经营现金承压',cash-abs(cash)*drop,0,f'预计可用于偿债的现金下降{drop:.0%}，利率不变。','用户可调敏感性；默认20%，不是行业违约概率或统一标准'),
        item('receivable','回款延迟',cash-revenue/365*delay,0,f'应收账款回收延迟{delay:.1f}天，增加占用＝预计收入÷365×延迟天数。','用户指定回款延迟天数' if 'receivable_delay_days' in a else 'max(5天,历史最慢回款天数－最新回款天数)，最高30天；5/30天是测试边界'),
        item('margin','毛利率下降',cash-revenue*margin_drop,0,f'毛利率下降{margin_drop*100:.2f}个百分点，现金减少＝预计收入×降幅。','用户指定毛利率下降；假定成本增加全额影响现金、未计税盾' if 'margin_drop' in a else '三年毛利率极差，限制1—5个百分点；假定成本增加全额影响现金、未计税盾'),
        item('rate','融资成本上升',cash,up,f'新增融资年利率上升{up*100:.2f}个百分点，现金不变；不假设已有固定合同也同步加息。','默认+1个百分点为敏感性假设；可替换实际报价'),
        item('combined','现金下降且加息',cash-abs(cash)*drop,up,f'预计可用于偿债的现金下降{drop:.0%}，新增融资年利率上升{up*100:.2f}个百分点。','上述两项联合测试，不代表两项同时发生的概率')]
    prior_conservative=model.get('conservative_cash')
    if prior_conservative is not None and prior_conservative<min(s['annual_cash'] for s in scenarios):
        support=model['diagnostics']['support'];binding=min(support['scenarios'],key=lambda s:s['ocf']);drivers=binding['drivers']
        scenarios[-1]=item('combined','历史结构联合压力',prior_conservative,up,f"采用历史结构最紧情景：{binding['label']}；应收{drivers['dso']:.1f}天、存货{drivers['dio']:.1f}天、应付{drivers['dpo']:.1f}天、毛利率{drivers['gross_margin']:.2%}，扣维持性投资；新增年利率上升{up*100:.2f}个百分点。",'按企业三年实际不利参数构造，非市场预测；与校正现金取更低者')
    elif min(s['annual_cash'] for s in scenarios[:-1])<scenarios[-1]['annual_cash']:
        worst=min(scenarios[:-1],key=lambda s:s['annual_cash'])
        scenarios[-1]=item('combined','最紧现金情景且加息',worst['annual_cash'],up,worst['rule']+f' 同时新增融资年利率上升{up*100:.2f}个百分点。',worst['parameter_origin']+'；联合加息为敏感性假设')
    return dict(scenarios=scenarios,stress_cash=min(s['annual_cash'] for s in scenarios),rate_up=up,operating_ceiling=max(0,cost),delay_days=delay,margin_drop=margin_drop,
        note='压力数值是企业历史参考与显式敏感性假设；方法参考BCBS压力测试原则，没有统一监管数值要求。全年营业成本仅作生产经营用款上限，不等于已核实的资金缺口或授信。')

def annual_diagnosis(raw,model):
    d=model.get('diagnostics') or {};a=model['assumptions'];result=[]
    def money(v):return f'{v/1e8:,.6f}亿元'
    def add(title,text,link):result.append(dict(title=title,text=text,decision_link=link))
    lev=raw['total_liabilities']/raw['total_assets'] if raw['total_assets']>0 else 0
    ratio=raw['current_assets']/raw['current_liabilities'] if raw['current_liabilities']>0 else None
    add('资产负债分析',f"当前负债率{lev:.1%}，{'流动资产覆盖流动负债'+format(ratio,'.2f')+'倍' if ratio is not None else '流动负债为零，不计算流动比率'}。"+('负债已触及模型上限，应先改善资本结构。' if lev>=a['max_leverage'] else '尚有账面负债空间，但不能代替现金偿付能力。'),'形成杠杆约束；上限属于可调情景。')
    add('应收与固定资产分析',f"应收账款{money(raw['accounts_receivable'])}，固定资产{money(raw['fixed_assets'])}。分别支持应收质押与固定资产抵押的条件式资产池，账面金额不等于可获批额度。",'三类贷款均按12个月测算。需核对债权账期、权属和已占用担保；不自动滚动续贷。')
    bridges=d.get('working_bridges') or []
    if bridges:
        b=bridges[-1];change=b['nwc_change'];lead=max(b['components'],key=lambda c:abs(c['change']))
        from finbridge.data_contract import LABELS
        add('营运资金分析',f"最新年度周转资金占用{'增加' if change>=0 else '减少'}{money(abs(change))}，最大变化来自{LABELS[lead['key']]}。"+('增长占用现金，应核实是否为持续周转需求。' if change>0 else '历史占用释放不能当作未来必然到账。'),'用于需求匹配与回款延迟情景；全年营业成本只是经营用款上限。')
    prediction=(model.get('cash_prediction') or {}).get('future') or {}
    add('现金流分析',f"下一年校正经营现金{money(prediction.get('annual_operating',model['forecast_ocf']))}，扣维持性投资后预计可用于偿债的现金{money(model['cash'])}。"+('正现金仍需先覆盖旧债与安全余量。' if model['cash']>0 else '预计可用于偿债的现金为负，不支持新增债务。'),'形成现金偿付约束；只测算下一完整年度，不外推长期或精确月度现金。')
    attribution=d.get('roe_attribution')
    if attribution:
        lead=max(attribution['contributions'],key=lambda c:abs(c['value']))
        add('盈利归因',f"最近两年权益回报变化{attribution['change']*100:+.2f}个百分点，主要分项是{lead['label']}（{lead['value']*100:+.2f}个百分点）。这是代数归因，不是因果识别。",'解释利润变化、支撑毛利压力判断；不把利润增长直接换成更高贷款额度。')
    else:add('盈利归因','当前收入或权益条件不支持有效杜邦分解，暂停归因。','不据缺失或无效归因放大融资额度。')
    return result

def solve_year(raw,profile,model,products,stress):
    from finbridge.enterprise_model import unit_schedule,existing_schedule
    demand=profile['requested_amount']/10000;a=model['assumptions'];n=4;count=len(stress['scenarios']);size=9+count
    alpha=a.get('cvar_alpha',CVAR_ALPHA);weight=a.get('cvar_weight',CVAR_WEIGHT)
    cap=np.array([p['capacity']/10000 for p in products]);fees=np.array([p['fee_rate'] for p in products]);fixed=np.array([p['fixed_fee']/10000 for p in products])
    net=np.r_[1-fees,-fixed,np.zeros(1+count)];rows=[];lower=[];upper=[]
    def add(coef,lo=-np.inf,hi=np.inf):rows.append(np.pad(coef,(0,size-len(coef))));lower.append(lo);upper.append(hi)
    for i in range(n):
        c=np.zeros(size);c[i]=1;c[n+i]=-cap[i];add(c,hi=0)
        c=np.zeros(size);c[i]=-1;c[n+i]=min(cap[i],1.);add(c,hi=0)
    add(net,lo=0,hi=demand)
    add(np.r_[np.ones(n),np.zeros(n)],hi=max(0,a['max_leverage']*raw['total_assets']-raw['total_liabilities'])/10000)
    add(net,hi=stress['operating_ceiling']/10000)
    schedules=np.array([unit_schedule(p,12) for p in products]).T
    adverse=np.array([unit_schedule(p,12,stress['rate_up']) for p in products]).T
    existing=existing_schedule(raw,model,12)
    add(np.r_[adverse.sum(axis=0),np.zeros(n)],hi=max(0,stress['stress_cash']/a['target_coverage']-sum(existing))/10000)
    reserve=model['capex']*0+raw['cost_of_goods_sold']*a['reserve_days']/365
    # Timing sensitivity uses a uniform annual cash allocation, not a monthly forecast.
    for t in range(12):
        available=raw['cash_equivalents_balance']-reserve+stress['stress_cash']*(t+1)/12-sum(existing[:t+1])
        add(np.r_[adverse[:t+1].sum(axis=0),np.zeros(n)],hi=max(0,available)/10000)
    for j,scenario in enumerate(stress['scenarios']):
        shocked=np.array([sum(unit_schedule(p,12,scenario['rate_up'])) for p in products])
        row=np.zeros(size);row[:n]=shocked-schedules.sum(axis=0);row[8]=-1;row[9+j]=-1
        add(row,hi=(scenario['annual_cash']-model['cash'])/10000)
    bounds=Bounds(np.zeros(size),np.r_[cap,np.ones(n),np.full(1+count,np.inf)]);integer=np.r_[np.zeros(n),np.ones(n),np.zeros(1+count)]
    options=dict(time_limit=15,mip_rel_gap=1e-7)
    first=milp(-net,integrality=integer,bounds=bounds,constraints=LinearConstraint(rows,lower,upper),options=options)
    if not first.success:return dict(success=False,solver_status=int(first.status),message='未取得最优可行解，不发布融资金额。',amounts=[0.]*4,horizon=12)
    covered=float(net@first.x);add(net,lo=max(0,covered-1e-5))
    cost=np.r_[schedules.sum(axis=0)-1+fees,fixed,np.zeros(1+count)]
    cost[8]=weight;cost[9:]=weight/((1-alpha)*count)
    second=milp(cost,integrality=integer,bounds=bounds,constraints=LinearConstraint(rows,lower,upper),options=options)
    if not second.success:return dict(success=False,solver_status=int(second.status),message='成本优化未收敛，不发布近似最优结论。',amounts=[0.]*4,horizon=12)
    x=np.maximum(0,second.x[:4])*10000;x[x<.01]=0
    from finbridge.enterprise_model import _tail_mean
    losses=[max(0,model['cash']-s['annual_cash']+sum((sum(unit_schedule(p,12,s['rate_up']))-sum(unit_schedule(p,12)))*amount for p,amount in zip(products,x))) for s in stress['scenarios']]
    return dict(success=True,solver_status=int(second.status),horizon=12,amounts=x.tolist(),weight=weight,mip_gap=float(second.mip_gap),cvar=_tail_mean(losses,alpha),max_net=covered*10000,objective=float(second.fun*10000))

def evaluate_year(plan):
    from finbridge.enterprise_model import existing_schedule,unit_schedule
    model=plan['model'];raw=model['raw'];a=model['assumptions'];existing=existing_schedule(raw,model,12)
    tests=[]
    for scenario in plan['annual_context']['scenarios']:
        payment=sum((unit_schedule(c,12,scenario['rate_up'])*c['amount'] for c in plan['composition']),np.zeros(12))
        total=float(sum(existing+payment));cash=scenario['annual_cash'];ratio=cash/total if total>0 else None
        tests.append({**scenario,'dscr':ratio,'new_annual_service':float(sum(payment)),'existing_annual_service':float(sum(existing)),
            'total_service':total,'gap_to_target':max(0,a['target_coverage']*total-cash),'passed':cash>=a['target_coverage']*total-.1})
    base=tests[0];worst=max(tests,key=lambda s:(s['gap_to_target'],-s['dscr'] if s['dscr'] is not None else -math.inf));boundary=1-a['target_coverage']*base['total_service']/model['cash'] if model['cash']>0 else None
    alpha=a.get('cvar_alpha',CVAR_ALPHA);weight=a.get('cvar_weight',CVAR_WEIGHT)
    losses,cvar=tail_cash_pressure(tests,model['cash'],alpha)
    for s,loss in zip(tests,losses):s['tail_cash_pressure']=loss
    return dict(available=plan['available'],annual_scope=True,horizon=12,scenarios=tests,diagnostic_stress=tests,
        cash_decline_boundary=boundary,rate_increase_boundary=None,peak_service=base['total_service'],cash_shortfall_probability=None,cvar=cvar,
        cvar_alpha=alpha,cvar_weight=weight,scenario_weights=[1/len(tests)]*len(tests),cvar_details=cvar_explanation(tests,alpha),
        cvar_note=f'CVaR{alpha:.0%}：六个等权假设情景中，最差{1-alpha:.0%}权重的平均现金余量损失。损失＝max(0，基准偿债后余量－情景偿债后余量)；是余量下降，不是现金不足额或实际发生概率。',
        conclusion=f"本方案在{sum(x['passed'] for x in tests)}/{len(tests)}个明确情景中达到偿付安全线；最大现金补足额{worst['gap_to_target']/1e8:,.6f}亿元。这是条件检验，不是违约概率。",
        reverse_summary=(f'预计可用于偿债的现金下降约{boundary:.1%}将触及安全线。' if boundary is not None and boundary>=0 else '基准现金不足以达到安全线，应减少融资或改善现金。'),
        dimensions=[],assumptions=[plan['annual_context']['note'],'已有债务本息是财报余额代理；年度财报无法验证真实月度回款、合同到期和债权资格。'],
        actions=['取得实际报价与还款合同后复核成本。','核对应收债权账期、质押登记及担保覆盖，不自动假设到期续贷或替换债权。','实际回款或毛利弱于情景时，调整融资金额并重新验证。'])

def optimize_year(raw,profile,planning_stress=None):
    from finbridge.public_finance import public_model
    from finbridge.enterprise_model import product_rules,_assemble,verify_plan,decision_summary
    model=public_model(raw,profile)
    if not model['available']:return dict(available=False,status='三年财报未通过完整性检查',model=model,funding=dict(gap=profile['requested_amount'],debt_total=0.,unfunded_gap=profile['requested_amount']),composition=[])
    stress=annual_scenarios(raw,model,planning_stress)
    model['conservative_cash']=min(model.get('conservative_cash',stress['stress_cash']),stress['stress_cash'])
    stress['stress_cash']=model['conservative_cash']
    drop=max(0,1-stress['stress_cash']/model['cash']) if model['cash']>0 else model['assumptions']['cash_drop']
    planning=dict(cash_drop=drop,rate_up=stress['rate_up'])
    products=product_rules(raw,profile,model);sol=solve_year(raw,profile,model,products,stress)
    plan=_assemble(raw,profile,model,products,sol,planning);plan['annual_context']=stress;plan['strategy']='一年期融资组合';plan['frontier']=[]
    for c in plan['composition']:
        c['reason']={'credit':'无需在模型中占用抵押资产，12个月到期还本；额度以收入比例与偿付约束共同限定。','secured':'以独立固定资产池支持12个月生产经营周转，到期还本；须核实权属、已有抵押及评估值。','factoring':'以应收债权质押支持12个月生产经营周转；债权回收和质押覆盖须核实，不是半年保理的自动续作。','leasing':'本范围不配置设备融资。'}[c['id']]
    plan['funding']['note']='净用款需求扣除自行安排资金；手续费由融资本金支付。三类产品均按12个月测算，不默认续贷。'
    alpha=model['assumptions'].get('cvar_alpha',CVAR_ALPHA);weight=model['assumptions'].get('cvar_weight',CVAR_WEIGHT)
    plan['algorithm'].update(name='一年期MILP＋情景CVaR辅助权衡',objective=['最大覆盖净用款',f'同等覆盖下最小化一年成本＋{weight}×情景CVaR{alpha:.0%}'],samples=0,scenario_count=len(stress['scenarios']),risk_weight=weight,cvar_alpha=alpha,loss_definition='基准与压力情景的偿债后现金余量之差，负值取0；等权假设，不估计真实概率',diagnosis_basis='校正现金、历史周转与毛利情景、杠杆和经营用途边界',methods=['MILP：产品启用与金额变量；成本＋小权重情景CVaR，偿付硬约束保持',f'Rockafellar–Uryasev CVaR线性化；六情景等权、alpha={alpha:.0%}、lambda={weight}为显式偏好参数','BCBS：相关且透明的压力情景，具体幅度来自历史参考或假设'])
    plan['algorithm']['objective_value']=sol.get('objective')
    plan['algorithm']['alpha']=alpha
    plan['algorithm']['constraints'].append(dict(label='生产经营用款上限（预计营业成本代理）',sources=['revenue','cost_of_goods_sold'],value=stress['operating_ceiling']))
    plan['verification']=verify_plan(plan)
    plan['risk_evaluation']=evaluate_year(plan);plan['scenarios']=plan['risk_evaluation']['scenarios']
    plan['decision_summary']=decision_summary(plan)
    if model['gap']<=.01:
        plan['decision_summary']['text']='财报基础测算未显示经营现金缺口，应先核实新增周转预算并优先考虑自有资金。以下仅是在用户明确需求下的条件式融资测算。'+plan['decision_summary']['text']
    plan['repayment_note']='规划期与三类贷款均为12个月。应收质押须核实实际债权账期与担保覆盖；不默认续贷。年内支付时点仅作均匀现金分配下的敏感性检查，不是月度预测。'
    return plan
