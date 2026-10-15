"""Annual financial identities and scenario drivers, without trained predictors."""
from itertools import permutations
from finbridge.financial_history import annual_records
from finbridge.financial_methods import METHODS,driver_scenarios

WC = ('accounts_receivable','inventory','prepayments','accounts_payable','advance_receipts','contract_liabilities')
SIGNS = (1,1,1,-1,-1,-1)
REFERENCES = [
    dict(title='Nissim & Penman (2001)：财务比率与结构分析',url='https://doi.org/10.1023/A:1011338221623'),
    dict(title='Jaworski & Czerwonka (2024)：营运资金管理元分析',url='https://doi.org/10.1007/s40622-023-00372-x'),
    dict(title='IAS 7：现金流量表及现金调节',url='https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/'),
]

def complete(v,keys):
    return all(v.get(k) is not None for k in keys)

def nwc(v):
    return sum(v[k]*s for k,s in zip(WC,SIGNS)) if complete(v,WC) else None

def historical_issues(raw,cash_sensitivity=False):
    from finbridge.public_data import BLOCKS
    signed={k for defs in BLOCKS.values() for k,_,_,s in defs if s}
    issues=[]
    for row in annual_records(raw):
        v=row['values'];y=row['year'];tol=max(1,abs(v.get('total_assets') or 0)*1e-5)
        if any(x is not None and x<0 and k not in signed for k,x in v.items()):issues.append(f'{y}年度有不应为负的财报金额')
        if complete(v,('total_assets','total_liabilities','ending_equity')) and abs(v['total_assets']-v['total_liabilities']-v['ending_equity'])>tol:issues.append(f'{y}年度资产不等于负债加权益，请核对口径和单位')
        for part,total in [('current_assets','total_assets'),('current_liabilities','total_liabilities')]:
            if complete(v,(part,total)) and v[part]>v[total]+tol:issues.append(f'{y}年度流动项目超过合计')
        if complete(v,('total_assets','current_assets','fixed_assets')) and v['fixed_assets']>v['total_assets']-v['current_assets']+tol:issues.append(f'{y}年度固定资产超过非流动资产，请核对单位或重复科目')
        keys=('opening_cash_equivalents','operating_cash_flow','net_investing_cash_flow','net_financing_cash_flow','cash_effect_fx','cash_equivalents_balance')
        sensitivity_latest=cash_sensitivity and y==annual_records(raw)[-1]['year']
        if not sensitivity_latest and complete(v,keys) and abs(sum(v[k] for k in keys[:-1])-v[keys[-1]])>max(1,abs(v[keys[-1]])*1e-8):issues.append(f'{y}年度现金流量表期初、净现金变动与期末不一致，请核对取数')
    return issues

def build_diagnostics(raw,growth=0.):
    from finbridge.data_contract import LABELS
    records=annual_records(raw);profit=[];working=[];cash=[];attribution=None;bridges=[];support=None
    for row in records:
        v=row['values'];rev=v.get('revenue');cost=v.get('cost_of_goods_sold');assets=v.get('total_assets');eq=v.get('ending_equity')
        profit.append(dict(year=row['year'],revenue=rev,net_profit=v.get('net_profit'),gross_margin=(rev-cost)/rev if rev and cost is not None else None,net_margin=v['net_profit']/rev if rev and v.get('net_profit') is not None else None,roe=v['net_profit']/eq if eq and eq>0 and v.get('net_profit') is not None else None))
        working.append(dict(year=row['year'],nwc=nwc(v),receivable_days=v['accounts_receivable']/rev*365 if rev and v.get('accounts_receivable') is not None else None,inventory_days=v['inventory']/cost*365 if cost and v.get('inventory') is not None else None,payable_days=v['accounts_payable']/cost*365 if cost and v.get('accounts_payable') is not None else None))
        keys=('opening_cash_equivalents','operating_cash_flow','net_investing_cash_flow','net_financing_cash_flow','cash_effect_fx','cash_equivalents_balance')
        cash.append(dict(year=row['year'],operating=v.get('operating_cash_flow'),investing=v.get('net_investing_cash_flow'),financing=v.get('net_financing_cash_flow'),reconciliation=sum(v[k] for k in keys[:-1])-v[keys[-1]] if complete(v,keys) else None))
    pairs=[(p,c) for p,c in zip(records,records[1:]) if c['year']==p['year']+1]
    for row in working:
        row['cash_cycle_days']=row['receivable_days']+row['inventory_days']-row['payable_days'] if all(row[k] is not None for k in ('receivable_days','inventory_days','payable_days')) else None
    for old,new in pairs:
        p,c=old['values'],new['values']
        if complete(p,WC+('operating_cash_flow',)) and complete(c,WC+('operating_cash_flow',)):
            delta=nwc(c)-nwc(p)
            bridges.append(dict(year=new['year'],nwc_change=delta,pre_wc_cash_proxy=c['operating_cash_flow']+delta,components=[dict(key=k,change=(c[k]-p[k])*s) for k,s in zip(WC,SIGNS)]))
    if pairs:
        old,new=pairs[-1];p,c=old['values'],new['values'];keys=('net_profit','revenue','total_assets','ending_equity')
        if complete(p,keys) and complete(c,keys) and all(v[k]>0 for v in (p,c) for k in keys[1:]):
            factors=lambda v:[v['net_profit']/v['revenue'],v['revenue']/v['total_assets'],v['total_assets']/v['ending_equity']]
            before,after=factors(p),factors(c);parts=[0.,0.,0.]
            def product(x):return x[0]*x[1]*x[2]
            for order in permutations(range(3)):
                x=before.copy()
                for i in order:
                    a=product(x);x[i]=after[i];parts[i]+=(product(x)-a)/6
            attribution=dict(from_year=old['year'],to_year=new['year'],change=product(after)-product(before),contributions=[dict(label=k,value=x) for k,x in zip(('净利率变化','资产效率变化','杠杆变化'),parts)],residual=product(after)-product(before)-sum(parts),basis='两年均用期末资产及权益，六种替换顺序平均的精确代数归因；不是经营因果判断。')
        expense=('cost_of_goods_sold','selling_expense','administrative_expense','research_expense','finance_expense','taxes_surcharges','income_tax_expense')
        if complete(p,('revenue','net_profit')+expense) and complete(c,('revenue','net_profit')+expense):
            components=[dict(key='revenue',value=c['revenue']-p['revenue'])]+[dict(key=k,value=p[k]-c[k]) for k in expense]
            expense_bridge=dict(from_year=old['year'],to_year=new['year'],change=c['net_profit']-p['net_profit'],components=components,residual=c['net_profit']-p['net_profit']-sum(x['value'] for x in components))
        else:expense_bridge=None
    else:expense_bridge=None
    # Use only full consecutive, comparable annual bridges. The range is a historical
    # sensitivity scenario, never a statistically calibrated forecast interval.
    if raw.get('financial_history'):support=driver_scenarios(records,bridges,growth)
    insights=[];improvements=[]
    if attribution:
        largest=max(attribution['contributions'],key=lambda x:abs(x['value']))
        insights.append(dict(module='profit',title='回报变化主要来自哪里',text=f"{attribution['from_year']}—{attribution['to_year']}年权益回报变化{attribution['change']*100:+.2f}个百分点，主要分项为{largest['label']}（{largest['value']*100:+.2f}个百分点）。",action='如果主要来自杠杆增加，不能据此提高现金借款能力；优先检查经营效率和利润兑现。',method_ids=['structure','shapley']))
    if bridges:
        last=bridges[-1];driver=max(last['components'],key=lambda x:abs(x['change']))
        from finbridge.data_contract import LABELS
        insights.append(dict(module='working',title='资金沉淀在哪个环节',text=f"最近年度经营性净营运资本变化{last['nwc_change']/1e8:+.6f}亿元；最大变动项是{LABELS[driver['key']]}，对应资金占用变化{driver['change']/1e8:+.6f}亿元。",action='增加占用会挤压现金；应收、存货、预付款先查回收节奏，应付与客户预付款则核对付款义务。',method_ids=['working','cash']))
    if working and records:
        v=records[-1]['values'];w=working[-1]
        for key,label,flow in [('receivable_days','回款提前','revenue'),('inventory_days','存货周转提前','cost_of_goods_sold')]:
            if w[key] is not None and w[key]>0 and v.get(flow,0)>0:
                days=min(10,w[key]);amount=v[flow]/365*days
                improvements.append(dict(label=label,days=days,cash_release_proxy=amount,formula=f'{LABELS[flow]}÷365×改善天数',note='仅为同规模占用敏感性；没有实际回款或销售安排，不计入融资来源。'))
    return dict(years=[r['year'] for r in records],profit_trend=profit,roe_attribution=attribution,expense_bridge=expense_bridge,working_capital=working,working_bridges=bridges,cash_reconciliation=cash,support=support,insights=insights,improvements=improvements,methods=METHODS,references=REFERENCES,limitations=['缺少连续两年完整科目时不做对应动态归因；空白不补零。','周转天数统一采用期末余额代理，便于跨年比较；与平均余额指标分开。','三份年报不能训练可靠预测模型，未来数值均为显式情景。'])
