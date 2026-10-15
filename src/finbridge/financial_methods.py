"""Method provenance. Research supports methods, not application parameter values."""
METHODS={
 'structure':dict(title='基础财务结构与盈利分解',basis='Nissim & Penman (2001)',url='https://www.columbia.edu/~dn75/Ratio_analysis_and_equity_valuation_From_research_to_practice.pdf',application='分别观察经营效率、盈利与杠杆，不把高权益回报直接解释成低信用风险。'),
 'shapley':dict(title='顺序无关的变化归因',basis='Shapley (1953)',url='https://doi.org/10.1515/9781400881970-018',application='三因子六种替换顺序的边际变化平均；贡献与总变化精确闭合，是代数分配而非因果识别。'),
 'history':dict(title='多年度、核心项目的分析设计',basis='Binz、Schipper & Standridge (2025)',url='https://doi.org/10.1016/j.jacceco.2025.101805',application='参考拆分核心项目与利用历史信息的设计思路；本系统没有训练或复现该论文的机器学习预测器。'),
 'working':dict(title='营运资金与资金占用',basis='Jaworski & Czerwonka (2024)',url='https://doi.org/10.1007/s40622-023-00372-x',application='用周转周期定位资金占用；元分析不能给每个企业规定统一最优账期，历史不利值仅作情景。'),
 'cash':dict(title='现金流量分类与勾稽',basis='IAS 7；现金流量表会计恒等关系',url='https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/',application='期初现金加三类净现金及汇率影响与期末核对；余额变化前现金是代理，不能冒充间接法完整调整。'),
 'cvar':dict(title='成本与尾部现金缺口优化',basis='Rockafellar & Uryasev (2000)',url='https://uryasev.github.io/publications/',application='采用CVaR线性化，最差5%情景平均储备缺口与融资成本共同优化；权重是可调整偏好。'),
 'stress':dict(title='压力、逆向压力与独立验证',basis='Basel Committee (2018) Stress testing principles',url='https://www.bis.org/bcbs/publ/d450.pdf',application='借鉴敏感性、情景、逆向压力和模型验证框架；不是声称本企业工具符合银行监管认证。'),
}

def driver_scenarios(records,bridges,growth):
    """Explicit historical-reference scenarios, not estimated probabilities."""
    if not records or not bridges or bridges[-1]['year']!=records[-1]['year']:return None
    from finbridge.deep_diagnostics import WC,nwc,complete
    latest=records[-1]['values']
    if not complete(latest,WC+('revenue','cost_of_goods_sold')) or latest['revenue']<=0 or latest['cost_of_goods_sold']<=0:return None
    observations=[r for r in records if complete(r['values'],WC+('revenue','cost_of_goods_sold')) and r['values']['revenue']>0 and r['values']['cost_of_goods_sold']>0]
    def ratios(v):
        return dict(dso=v['accounts_receivable']/v['revenue']*365,dio=v['inventory']/v['cost_of_goods_sold']*365,dpo=v['accounts_payable']/v['cost_of_goods_sold']*365,prepay=v['prepayments']/v['cost_of_goods_sold'],customers=(v['advance_receipts']+v['contract_liabilities'])/v['revenue'],gross_margin=1-v['cost_of_goods_sold']/v['revenue'])
    current=ratios(latest);historical=[ratios(r['values']) for r in observations]
    adverse={k:(min if k in {'dpo','customers','gross_margin'} else max)(r[k] for r in historical) for k in current}
    rev=latest['revenue']*(1+growth);start=nwc(latest)
    baseline_margin=bridges[-1]['pre_wc_cash_proxy']/latest['revenue']
    margins=[b['pre_wc_cash_proxy']/next(r['values']['revenue'] for r in records if r['year']==b['year']) for b in bridges if next(r['values'].get('revenue') or 0 for r in records if r['year']==b['year'])>0]
    def scenario(key,label,r,margin):
        cost=rev*(1-r['gross_margin'])
        stocks=dict(accounts_receivable=rev*r['dso']/365,inventory=cost*r['dio']/365,prepayments=cost*r['prepay'],accounts_payable=cost*r['dpo']/365,customer_advances=rev*r['customers'])
        target=stocks['accounts_receivable']+stocks['inventory']+stocks['prepayments']-stocks['accounts_payable']-stocks['customer_advances']
        gross_loss=rev*max(0,current['gross_margin']-r['gross_margin'])
        before=rev*margin-gross_loss;cash=before-(target-start)
        return dict(id=key,label=label,ocf=cash,projected_revenue=rev,projected_cost=cost,nwc_target=target,nwc_increase=target-start,gross_margin_cash_loss=gross_loss,pre_wc_cash=before,drivers=r,stocks=stocks,cash_margin=margin)
    turnover={**current,**{k:adverse[k] for k in ('dso','dio','dpo','prepay','customers')}}
    scenarios=[scenario('base','基准：保持近期经营与周转结构',current,baseline_margin),scenario('conversion','现金转化回到历史较低水平',current,min(margins)),scenario('margin','毛利率回到历史较低水平',{**current,'gross_margin':adverse['gross_margin']},baseline_margin),scenario('turnover','回款与库存回到历史不利水平',turnover,baseline_margin),scenario('combined','利润率与周转同时承压',{**turnover,'gross_margin':adverse['gross_margin']},baseline_margin)]
    base=scenarios[0]['ocf'];worst=min(scenarios,key=lambda x:x['ocf'])
    for s in scenarios:s['cash_change']=s['ocf']-base
    return dict(base_ocf=base,conservative_ocf=worst['ocf'],historical_cash_candidates=[s['ocf'] for s in scenarios],scenarios=scenarios,binding_scenario=worst['label'],years=[r['year'] for r in records],nwc_change=bridges[-1]['nwc_change'],formula='经营现金＝情景收入×变动前现金/收入代理－毛利率下降对应成本增加－净营运资本增量；应收随收入及回款天数、存货与应付随成本及周转天数变化。',limitations='历史不利参数组合是保守敏感性设定，不是发生概率。假设成本增加全部影响现金，未估计税盾及非现金成本；余额变化含汇率、并购和重分类，尚未识别真实月度季节性。',method_ids=['working','cash','history'])
