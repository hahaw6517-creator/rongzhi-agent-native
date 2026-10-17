from copy import deepcopy
import json
import time
import numpy as np
import pytest
from finbridge.public_data import public_example,parse_simple_statement
from finbridge.public_finance import public_profile
from finbridge.enterprise_model import optimize_financing,verify_plan,_tail_mean,product_rules,ENGINE
from finbridge.workflow import DiligenceRun,report_markdown
from finbridge.decision_chat import DecisionConversation,confirm_proposal
from finbridge.config import Settings
from finbridge.data import load_uploaded_financial_data
from finbridge.public_template import public_template_xlsx,public_template_csv

SETTINGS=Settings('test','https://example.invalid','test')

@pytest.fixture(scope='module')
def enterprise_run():
    raw=public_example();raw.update(operating_cash_flow=2800000,prior_operating_cash_flow=2400000)
    profile=public_profile(raw,dict(decision_engine=ENGINE,requested_amount=600000,requested_months=36,requested_purpose='设备购置'))
    return DiligenceRun(raw,profile,'融资组合','虚构测试').local()

def test_full_workflow_produces_separate_modules_and_grounded_report(enterprise_run):
    r=enterprise_run;p=r['outputs']['optimize_financing_portfolio']
    assert r['status']=='已完成' and all(e['status']=='完成' for e in r['events'])
    assert len(r['events'])==10
    assert r['financial_analysis']['available'] and len(r['financial_analysis']['findings'])>=7
    assert len(r['financial_analysis']['forecast']['months'])==36
    assert r['outputs']['verify_decision']['passed']
    assert p['funding']['debt_total']>p['funding']['net_proceeds']>0
    assert abs(p['funding']['net_proceeds']+p['funding']['unfunded_gap']-600000)<.2
    assert len(p['frontier'])==3 and all(s['verified'] for s in p['frontier'])
    assert len({tuple(s['amounts']) for s in p['frontier']})>=1
    assert p['algorithm']['solver']=='SciPy / HiGHS'
    assert p['algorithm']['optimality_gap']<=1e-7
    risk=r['outputs']['assess_risk']['enterprise_risk']
    assert risk['samples']==3000 and risk['seed']!=p['algorithm']['seed']
    assert sum(risk['histogram']['counts'])==3000
    assert risk['cvar']>=risk['var']>=0
    report=report_markdown(r)
    assert '财务判断' in report and '融资策略' in report and '风险与执行条件' in report
    assert '全部指标' not in report and len(report)<4500
    json.dumps(r,allow_nan=False)

@pytest.mark.parametrize('extension,content',[('xlsx',lambda:public_template_xlsx(True)),('csv',lambda:public_template_csv(True))])
def test_three_column_template_roundtrip(extension,content):
    row=load_uploaded_financial_data('企业.'+extension,content()).iloc[0].to_dict()
    assert row['revenue']==9600000 and row['company_name']
    assert row['public_provenance']['revenue']['cell'].startswith('C')
    assert 'confirmed_credit_limit' not in row

def test_blank_optional_values_remain_missing_and_unit_conversion():
    import pandas as pd
    frame=pd.DataFrame([['类别','科目','数值'],['企业信息','企业名称','测试'],['企业信息','报告期','2025年度'],['企业信息','金额单位','万元'],['利润表','营业收入',120],['利润表（可选）','营业利润','']])
    row=parse_simple_statement({'企业财务数据':frame}).iloc[0]
    assert row['revenue']==1200000 and row['operating_profit'] is None

def test_cvar_handles_fractional_tails_and_ties():
    assert _tail_mean([0,0,10,20],.5)==15
    assert _tail_mean([1]*128)==1
    assert _tail_mean([0,10,20],.5)==pytest.approx((20+5)/1.5)

def test_independent_verifier_detects_amount_fee_and_rule_tampering(enterprise_run):
    p=deepcopy(enterprise_run['outputs']['optimize_financing_portfolio'])
    p['funding']['total_assumed_interest']+=999
    assert not verify_plan(p)['passed']
    p=deepcopy(enterprise_run['outputs']['optimize_financing_portfolio'])
    c=next(c for c in p['composition'] if c['amount']>0)
    c.update(capacity=1e12,amount=1e9)
    assert not verify_plan(p)['passed']
    p=deepcopy(enterprise_run['outputs']['optimize_financing_portfolio'])
    p['composition'][1]['fee_rate']=0
    assert not verify_plan(p)['passed']

def test_unavailable_data_still_delivers_missing_report():
    raw=public_example();raw['capital_expenditure']=None
    r=DiligenceRun(raw,dict(decision_engine=ENGINE,requested_amount=600000),'融资组合','测试').local()
    assert r['status']=='已完成'
    assert not r['outputs']['verify_decision']['passed']
    assert not r['outputs']['optimize_financing_portfolio']['available']
    assert 'capital_expenditure' in r['financial_analysis']['missing']


@pytest.mark.parametrize('key',['total_assets','total_liabilities','current_assets','current_liabilities','cash_equivalents_balance','revenue','cost_of_goods_sold','net_profit','operating_cash_flow','capital_expenditure','short_term_debt','long_term_debt','current_portion_long_term_debt'])
def test_every_missing_required_value_delivers_a_blocked_result(key):
    raw=public_example();raw[key]=None
    r=DiligenceRun(raw,dict(decision_engine=ENGINE,requested_amount=600000),'融资组合','测试').local()
    assert r['status']=='已完成' and not r['outputs']['verify_decision']['passed']
    assert key in r['financial_analysis']['missing']


def test_thirteen_required_lines_work_with_all_optional_cells_blank():
    from finbridge.public_finance import NEEDED
    from finbridge.public_data import PUBLIC_LABELS
    raw=public_example()
    for k in PUBLIC_LABELS:
        if k not in NEEDED:raw[k]=None
    raw['operating_cash_flow']=2800000
    r=DiligenceRun(raw,dict(decision_engine=ENGINE,requested_amount=600000,requested_months=36,requested_purpose='设备购置'),'融资组合','测试').local()
    assert r['status']=='已完成' and r['outputs']['verify_decision']['passed']
    assert r['financial_analysis']['forecast']['volatility']==.2
    assert not next(x for x in r['outputs']['match_routes'] if x['id']=='factoring')['enabled']

def test_cash_stress_can_rule_out_all_new_debt_with_clear_failure():
    raw=public_example();raw['operating_cash_flow']=-200000
    r=DiligenceRun(raw,dict(decision_engine=ENGINE,requested_amount=600000),'融资组合','测试').local()
    p=r['outputs']['optimize_financing_portfolio']
    assert p['funding']['debt_total']==0
    assert not p['verification']['passed']
    assert '未通过' in p['decision_summary']['text']

def test_product_rules_are_not_industry_or_size_gated(enterprise_run):
    raw={**enterprise_run['raw_public'],'industry':'餐饮服务','region':'四川成都'}
    p=enterprise_run['input_profile']
    model=enterprise_run['public_analysis']
    products=product_rules(raw,{**p,'requested_purpose':'经营周转'},model)
    assert len(products)==4 and all(x['id'] for x in products)
    assert any(x['enabled'] for x in products)
    assert not next(x for x in products if x['id']=='leasing')['enabled']

def test_dialogue_requires_confirmation_and_no_leaves_data_unchanged(enterprise_run):
    agent=DecisionConversation(enterprise_run,SETTINGS,client=object())
    proposed=agent.execute('recalculate_plan',{'changes':{'requested_amount':500000,'requested_months':48}},'融资需求改成50万元，期限48个月')
    assert proposed['awaiting_confirmation'] and agent.candidate is None
    assert agent.current==enterprise_run
    cancelled=confirm_proposal(enterprise_run,agent.pending,False,None)
    assert cancelled['candidate'] is None and not cancelled['assistant']['saved_version']
    accepted=confirm_proposal(enterprise_run,agent.pending,True,None)
    new=accepted['candidate']
    assert new['id']!=enterprise_run['id'] and new['raw_public']==enterprise_run['raw_public']
    assert new['input_profile']['requested_amount']==500000 and new['input_profile']['requested_months']==48
    assert new['outputs']['verify_decision']['passed']

def test_statement_correction_is_explicit_and_checked_before_commit(enterprise_run):
    agent=DecisionConversation(enterprise_run,SETTINGS,client=object())
    with pytest.raises(ValueError):agent.execute('propose_statement_correction',{'changes':{'revenue':1e6}},'如果收入下降怎么办？')
    agent.execute('propose_statement_correction',{'changes':{'operating_cash_flow':3000000}},'更正报表，经营现金流改成300万元')
    result=confirm_proposal(enterprise_run,agent.pending,True,None)
    assert result['candidate']['raw_public']['operating_cash_flow']==3000000
    assert result['candidate']['confirmed_raw_update']
    assert enterprise_run['raw_public']['operating_cash_flow']==2800000
    agent.execute('propose_statement_correction',{'changes':{'total_assets':1000}},'更正总资产为1000元')
    with pytest.raises(ValueError):confirm_proposal(enterprise_run,agent.pending,True,None)


def test_api_correction_confirmation_updates_inputs_atomically_and_rejects_replay(tmp_path,monkeypatch,enterprise_run):
    import finbridge.working_capital_year as annual
    monkeypatch.setattr(annual,'year_profile',lambda profile=None:dict(profile or {}))
    from starlette.testclient import TestClient
    import finbridge.web_api as api
    import finbridge.decision_chat as module
    from types import SimpleNamespace
    class Client:
        def __init__(self):self.round=0
        @property
        def chat(self):return SimpleNamespace(completions=self)
        def create(self,**kwargs):
            self.round+=1
            name='read_analysis' if self.round==1 else 'propose_statement_correction'
            args={} if self.round==1 else dict(changes={'operating_cash_flow':3000000})
            call=SimpleNamespace(id='call'+str(self.round),function=SimpleNamespace(name=name,arguments=json.dumps(args)))
            msg=SimpleNamespace(content=None,tool_calls=[call],model_dump=lambda **_:dict(role='assistant',tool_calls=[dict(id=call.id,type='function',function=dict(name=name,arguments=json.dumps(args)))]))
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    original=module.DecisionConversation
    class Agent(original):
        def __init__(self,*a,**kw):super().__init__(*a,**kw,client=Client())
    monkeypatch.setattr(module,'DecisionConversation',Agent)
    monkeypatch.setattr('finbridge.model_resolver.load_settings',lambda:SETTINGS)
    with TestClient(api.create_app(database_path=tmp_path/'correct.sqlite3')) as client:
        client.get('/api/bootstrap')
        assert client.post('/api/company',json={'data':enterprise_run['raw_public'],'profile':enterprise_run['input_profile']}).status_code==200
        start=client.post('/api/runs',json={'profile':enterprise_run['input_profile']}).json()
        for _ in range(1000):
            r=client.get('/api/runs/'+start['id']).json()
            if r['status']!='执行中':break
            time.sleep(.01)
        assert r['status']=='已完成'
        path='/api/runs/'+r['id']+'/conversation'
        proposal=client.post(path,json={'message':'更正报表，经营现金流改成300万元'}).json()['messages'][-1]['pending_update']
        assert client.get('/api/bootstrap').json()['data']['operating_cash_flow']==2800000
        # Numeric values in confirmation are rejected: only the stored proposal is executable.
        assert client.post(path+'/confirm',json={'proposal_id':proposal['id'],'confirmed':True,'changes':{'revenue':1}}).status_code==400
        response=client.post(path+'/confirm',json={'proposal_id':proposal['id'],'confirmed':True})
        assert response.status_code==200,response.text
        head=response.json()['head_run_id']
        b=client.get('/api/bootstrap').json()
        assert b['data']['operating_cash_flow']==3000000 and b['active_run_id']==head
        assert client.get('/api/runs/'+r['id']).json()['raw_public']['operating_cash_flow']==2800000
        assert client.get('/api/runs/'+head).json()['raw_public']['operating_cash_flow']==3000000
        assert client.post(path+'/confirm',json={'proposal_id':proposal['id'],'confirmed':True}).status_code==409
        client.cookies.clear()
        assert client.get('/api/runs/'+head+'/conversation').status_code==404
