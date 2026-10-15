from copy import deepcopy
import io
import json
import pandas as pd
import pytest
from starlette.testclient import TestClient
from finbridge.real_case import real_case
from finbridge.public_template import annual_template_rows,annual_template_csv,annual_template_xlsx
from finbridge.public_data import parse_public_blocks
from finbridge.data_contract import completeness
from finbridge.public_finance import public_model,public_profile,validate_request
from finbridge.working_capital_year import year_profile
from finbridge.enterprise_model import optimize_financing,financial_analysis,verify_plan
from finbridge.cash_forecast import cash_forecast
from finbridge.web_api import create_app,validate_profile
from finbridge.workflow import DiligenceRun
from finbridge.decision_chat import tools_schema,validate_grounded_numbers
from finbridge.enterprise_report import enterprise_report_markdown


def case():
    c=real_case();return c['data'],public_profile(c['data'],c['profile'])


def test_relative_headers_roundtrip_and_explicit_years():
    rows=annual_template_rows(True)
    assert rows[0]==['类别','科目','最新年度','上一年度','上两年度']
    assert rows[1][2:]==[2025,2024,2023]
    raw=parse_public_blocks({'财报':pd.DataFrame(rows)}).iloc[0].to_dict()
    assert completeness(raw)['complete']
    assert raw['revenue']==28873380466.76 and raw['financial_history'][0]['year']==2023
    rows[1][2:]=[2021,2020,2019]
    raw=parse_public_blocks({'财报':pd.DataFrame(rows)}).iloc[0].to_dict()
    assert raw['report_period']=='2021年度'
    for bad in ([2025,2023,2022],['',2024,2023],[2026,2025,2024]):
        rows[1][2:]=bad
        with pytest.raises(ValueError):parse_public_blocks({'财报':pd.DataFrame(rows)})


def test_forecast_error_is_transferred_with_cap_and_holdout_separation():
    d,p=case();f=cash_forecast(d,calibrate=True);u=f['future'];v=f['validation']
    bound=max(abs(u['uncalibrated_operating']),abs(d['operating_cash_flow']))*.3
    assert u['calibration_adjustment']==pytest.approx(max(-bound,min(bound,-v['error']*.5)))
    assert u['annual_operating']==pytest.approx(u['uncalibrated_operating']+u['calibration_adjustment'])
    changed=deepcopy(d);changed['operating_cash_flow']*=2
    assert cash_forecast(changed,calibrate=True)['validation']['annual_operating']==v['annual_operating']
    assert public_model(d,p)['forecast_ocf']==u['annual_operating']


@pytest.mark.parametrize('changes',[{'requested_months':36},{'requested_purpose':'设备购置'},{'decision_scope':None,'requested_months':60}])
def test_scope_cannot_be_bypassed(changes):
    d,p=case()
    with pytest.raises(Exception):validate_profile(changes,p)
    with pytest.raises(ValueError):validate_request({**p,**changes,'decision_scope':'working-capital-12m'})


def test_single_plan_twelve_months_fees_and_scenario_rules():
    d,p=case();p={**p,'requested_amount':600000.,'secured_advance_ratio':0.,'factoring_advance_ratio':0.}
    plan=optimize_financing(d,p)
    assert plan['available'] and plan['verification']['passed'],plan
    assert len([c for c in plan['composition'] if c['amount']>.01])==1
    assert plan['funding']['debt_total']>600000
    assert plan['funding']['unfunded_gap']<=.10001
    assert all(c['months']==12 for c in plan['composition'])
    assert plan['composition'][-1]['capacity']==0
    assert not plan['frontier'] and plan['algorithm']['samples']==0
    assert len(plan['risk_evaluation']['scenarios'])>=6
    assert all(s['rule'] and s['parameter_origin'] for s in plan['risk_evaluation']['scenarios'])
    assert plan['risk_evaluation']['cash_shortfall_probability'] is None
    assert plan['algorithm']['risk_weight']==.1 and plan['algorithm']['cvar_alpha']==.8
    assert plan['cvar']==pytest.approx(plan['risk_evaluation']['cvar'],abs=.1)
    assert plan['algorithm']['objective_value']==pytest.approx(plan['funding']['total_assumed_interest']+plan['funding']['fees_due']+.1*plan['cvar'],abs=.2)
    assert plan['annual_context']['stress_cash']<=min(s['annual_cash'] for s in plan['annual_context']['scenarios'])
    broken=deepcopy(plan);broken['funding']['fees_due']+=10000
    assert not verify_plan(broken)['passed']
    broken=deepcopy(plan);broken['cvar']+=10000
    assert not verify_plan(broken)['passed']


def test_cvar_measures_margin_erosion_and_fractional_tail():
    from finbridge.working_capital_year import tail_cash_pressure
    tests=[dict(id='base' if i==0 else str(i),annual_cash=100-i*10,total_service=25 if i==5 else 20) for i in range(6)]
    losses,cvar=tail_cash_pressure(tests,100)
    assert losses==[0,10,20,30,40,55]
    assert cvar==pytest.approx((55+.2*40)/1.2)
    assert all(s['annual_cash']>=1.2*s['total_service'] for s in tests)
    assert cvar>0  # can remain solvent while losing cash headroom


def test_annual_capacity_reuses_production_model_without_mutating_request():
    from finbridge.financing_capacity import estimate_capacity
    from finbridge.enterprise_model import optimize_financing
    d,p=case();before=deepcopy((d,p))
    result=estimate_capacity(d,p,compare_terms=True)
    assert (d,p)==before and len(result['cases'])==1
    c=result['primary'];assert c['verified'] and c['months']==12
    assert c['net_capacity']>p['requested_amount']
    assert c['net_capacity']==pytest.approx(4465022293.58,abs=1)
    assert c['stress_coverage']==pytest.approx(1.2,abs=1e-7)
    assert c['cvar_alpha']==.8 and c['cvar']>0
    assert len(c['composition'])==2
    assert '压力情景还款现金约束' in c['limiting_factors']
    confirmed=optimize_financing(d,{**p,**c['profile_changes']})
    assert confirmed['verification']['passed']
    assert confirmed['funding']['net_proceeds']==pytest.approx(c['net_capacity'],abs=1)


def test_capacity_chat_failure_does_not_claim_new_verification(monkeypatch):
    from test_decision_chat import ScriptedClient,SETTINGS
    import finbridge.financing_capacity as cap
    from finbridge.decision_chat import DecisionConversation
    d,p=case();r=DiligenceRun(d,p,'融资组合','上限测试').local()
    def broken(*args,**kwargs):raise KeyError('annual_context')
    monkeypatch.setattr(cap,'estimate_capacity',broken)
    bad=dict(reply='无依据融资金额999999999999万元',metric_keys=[],source_ids=[],follow_up=None)
    client=ScriptedClient([[('read_analysis',{}),('estimate_financing_capacity',{})],bad,bad])
    out=DecisionConversation(r,SETTINGS,client=client).respond('测算最大可融资额')
    msg=out['assistant']['content']
    assert '融资上限测算未完成' in msg and 'annual_context' not in msg
    assert '通过独立数学验证' not in msg and out['candidate'] is None


def test_capacity_chat_produces_verified_preview_and_adoption_needs_confirmation():
    from test_decision_chat import ScriptedClient,SETTINGS
    from finbridge.decision_chat import DecisionConversation
    d,p=case();r=DiligenceRun(d,p,'融资组合','上限测试').local();before=deepcopy(r)
    client=ScriptedClient([[('read_analysis',{}),('estimate_financing_capacity',{})],dict(reply='上限测算已完成，见量化卡，当前报告未改变。',metric_keys=[],source_ids=[],follow_up=None)])
    agent=DecisionConversation(r,SETTINGS,client=client)
    out=agent.respond('保持12个月和生产经营周转用途，测算最大可融资额')
    assert out['assistant']['capacity_result']['primary']['verified']
    assert r==before and out['candidate'] is None and not out['assistant']['pending_update']
    proposal=agent.execute('propose_capacity_adjustment',{},'采用刚才测算的融资上限')['proposal']
    assert proposal and agent.candidate is None and r==before


def test_five_diagnoses_full_workflow_and_report():
    d,p=case();r=DiligenceRun(d,p,'融资组合','一年期测试').local()
    assert r['status']=='已完成' and r['outputs']['verify_decision']['passed']
    a=r['financial_analysis'];assert a['forecast']['horizon']==12
    assert [x['title'] for x in a['year_diagnosis']]==['资产负债分析','应收与固定资产分析','营运资金分析','现金流分析','盈利归因']
    text=enterprise_report_markdown(r)
    assert '误差校正' in text and '风险情景与规则' in text
    assert '3000条' not in text and '95% CVaR' not in text
    future=a['forecast']['history_prediction']['future']
    validate_grounded_numbers(f"校正后经营现金{future['annual_operating']/10000:.2f}万元。",r,r)
    specs=tools_schema(r['outputs']['calculate_ratios'],True,True)
    for spec in specs:
        props=spec['function']['parameters']['properties']
        if spec['function']['name'] in {'recalculate_plan','simulate_scenario'}:
            assert props['changes']['properties']['requested_months']['enum']==[12]


def test_native_scope_downloads_and_rejects_old_retrieval(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'annual.db')) as c:
        b=c.get('/api/bootstrap').json()
        assert b['profile']['requested_months']==12 and b['profile']['requested_purpose']=='经营周转'
        assert c.post('/api/company',json={'data':b['data'],'profile':{'requested_months':36}}).status_code==400
        assert c.post('/api/runs',json={'profile':{'requested_purpose':'设备购置'}}).status_code==400
        assert c.post('/api/listed-statements',json={}).status_code in (404,405)
        reply=c.get('/api/template?example=1');assert reply.status_code==200
        frames=pd.read_excel(io.BytesIO(reply.content),sheet_name=None,header=None)
        raw=parse_public_blocks(frames).iloc[0].to_dict();assert completeness(raw)['complete']
        assert list(frames.values())[0].iloc[0,2:5].tolist()==['最新年度','上一年度','上两年度']


def test_annual_chat_amount_confirmation_preserves_scope_and_facts(tmp_path,monkeypatch):
    import finbridge.web_api as api
    import finbridge.decision_chat as chat
    from finbridge.config import Settings
    from test_decision_chat import ScriptedClient,wait_run
    original=chat.DecisionConversation
    class Agent(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs,client=ScriptedClient([[('recalculate_plan',{'changes':{'requested_amount':800000.}})],dict(reply='已准备金额调整，请确认后重新分析。',metric_keys=[],source_ids=[],follow_up=None)]))
    monkeypatch.setattr(chat,'DecisionConversation',Agent)
    monkeypatch.setattr(api,'load_settings',lambda:Settings('test','https://example.invalid','test'))
    with TestClient(api.create_app(database_path=tmp_path/'chat-year.db')) as c:
        c.get('/api/bootstrap');start=c.post('/api/runs',json={'profile':{'requested_amount':600000.},'use_ai':False})
        assert start.status_code==202,start.text
        r=wait_run(c,start.json()['id']);path='/api/runs/'+r['id']+'/conversation'
        response=c.post(path,json={'message':'融资需求改成80万元，保持一年生产经营周转'})
        assert response.status_code==200,response.text
        proposal=response.json()['messages'][-1]['pending_update']
        updated=c.post(path+'/confirm',json={'proposal_id':proposal['id'],'confirmed':True})
        assert updated.status_code==200,updated.text
        head=c.get('/api/runs/'+updated.json()['head_run_id']).json()
        assert head['input_profile']['requested_amount']==800000
        assert head['input_profile']['requested_months']==12 and head['input_profile']['requested_purpose']=='经营周转'
        assert head['raw_public']==r['raw_public'] and head['outputs']['verify_decision']['passed']
        assert c.get('/api/runs/'+r['id']).json()['input_profile']['requested_amount']==600000
