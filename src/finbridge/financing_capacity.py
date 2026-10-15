"""Read-only capacity search, independent of a small requested funding amount."""
from copy import deepcopy
import math
from finbridge.public_finance import public_model,validate_request
from finbridge.enterprise_model import product_rules,_solve,_assemble,verify_plan,evaluate_risk,optimize_financing
from finbridge.workflow import fingerprint


def estimate_capacity(raw,profile,*,compare_terms=True,planning_stress=None):
    """Maximise net proceeds under unchanged financial assumptions; no LLM amounts."""
    original=deepcopy(profile)
    model=public_model(raw,profile)
    if not model['available']:
        return dict(available=False,reason='财报尚未通过核验，不能计算融资边界。',missing=model['missing'],issues=model['issues'])
    leverage=max(0,raw['total_assets']*model['assumptions']['max_leverage']-raw['total_liabilities'])
    # This is a software input limit, not a financial or lending limit.
    ceiling=min(1e10,leverage)
    months=int(profile.get('requested_months',24))
    terms=[12] if profile.get('decision_scope')=='working-capital-12m' else [months]+([n for n in (12,24,36,60) if n!=months] if compare_terms else [])
    cases=[]
    for term in terms:
        trial={**profile,'requested_amount':max(1.,ceiling),'requested_months':term}
        validate_request(trial)
        annual=profile.get('decision_scope')=='working-capital-12m'
        if annual:
            # Use the production solver, including annual scenarios and CVaR.
            # Only lift the user's small request; never relax financial limits.
            plan=optimize_financing(raw,trial,planning_stress=planning_stress)
            m=plan['model']
            v=plan.get('verification',dict(passed=False,checks=[],status='未取得可验证的最优解'))
        else:
            m=public_model(raw,trial);products=product_rules(raw,trial,m)
            sol=_solve(raw,trial,m,products,.5,planning_stress)
            plan=_assemble(raw,trial,m,products,sol,planning_stress)
            v=verify_plan(plan)
        f=plan['funding'];positive=plan['available'] and v['passed']
        double=min((s for s in plan.get('scenarios',[]) if s.get('dscr') is not None),key=lambda s:s['dscr'],default={}) if annual else next((s for s in plan['scenarios'] if s['id']=='double'),{})
        reasons=[]
        if not v['passed']:reasons += [c['label'] for c in v['checks'] if not c['passed']]
        if positive and double.get('dscr') is not None and abs(double['dscr']-m['assumptions']['target_coverage'])<.0001:reasons.append('压力情景还款现金约束')
        if positive and abs(f['debt_total']-leverage)<max(1.,leverage*1e-7):reasons.append('资产负债率情景上限')
        if positive and annual and abs(f.get('net_proceeds',0)-plan['annual_context']['operating_ceiling'])<max(1.,plan['annual_context']['operating_ceiling']*1e-7):reasons.append('生产经营用款规模上限')
        saturated=[c['name'] for c in plan['composition'] if c['enabled'] and c['capacity']>0 and abs(c['amount']-c['capacity'])<max(1.,c['capacity']*1e-7)]
        if saturated:reasons.append('资产或经营规模规则池：'+'、'.join(saturated))
        capped=positive and ceiling>=1e10-.01 and f.get('net_proceeds',0)>=ceiling-1
        if capped:reasons.append('已达到系统100亿元净需求测算上限，真实模型边界可能更高')
        if not reasons:reasons.append('用途、产品期限和逐月还款约束共同限制')
        cases.append(dict(months=term,net_capacity=max(0,f.get('net_proceeds',0)) if positive else 0.,
            gross_principal=f['debt_total'] if positive else 0.,fees=f['fees_due'] if positive else 0.,
            total_interest=f['total_assumed_interest'] if positive else 0.,cvar=plan.get('cvar'),cvar_alpha=plan.get('algorithm',{}).get('cvar_alpha'),
            stress_coverage=double.get('dscr'),verified=positive,system_capped=capped,limiting_factors=reasons,
            composition=[{k:c[k] for k in ('id','name','amount','months','rate','repayment','total_interest','total_fee')} for c in plan['composition'] if c['amount']>.01],
            verification=v,profile_changes=dict(requested_amount=math.floor(max(0,f.get('net_proceeds',0))*100)/100,requested_months=term)))
    primary=cases[0];best=max(cases,key=lambda c:c['net_capacity'])
    return dict(available=True,input_fingerprint=fingerprint(raw,profile),requested_amount=original.get('requested_amount',0),
        purpose=profile.get('requested_purpose','经营周转'),current_months=months,primary=primary,largest_case=best,cases=cases,
        additional_net_capacity=max(0,primary['net_capacity']-original.get('requested_amount',0)),
        note='本次为只读边界测算，未修改融资需求、财报、安全线或当前报告。边界是报表代理与产品规则下的条件式净资金上限，不是银行授信，也不是建议借满。',
        comparable_terms_note='当前模型固定12个月生产经营周转，仅解除原申请金额限制；未放松安全线和产品规则。' if profile.get('decision_scope')=='working-capital-12m' else '其他期限分别重新求解，不假定原产品能直接延长；如采用其他期限需同时确认金额和期限。')
