from copy import deepcopy
from datetime import date
from types import SimpleNamespace as NS
import io
import json
import httpx
import pandas as pd
import pytest
from finbridge.data_contract import CONTRACT,REQUIRED,completeness,rolling_years
from finbridge.public_data import parse_public_blocks,public_example
from finbridge.public_template import history_template_rows,history_template_csv,history_template_xlsx
from finbridge.public_finance import public_model,public_profile
from finbridge.enterprise_model import optimize_financing,product_rules,verify_plan
from finbridge.workflow import DiligenceRun
from finbridge.config import Settings
from finbridge.listed_financials import retrieve_a_share,MAPS
from finbridge.listed_agent import retrieve_with_agent

def raw_example():return parse_public_blocks({'财报':pd.read_csv(io.BytesIO(history_template_csv(True)),header=None)}).iloc[0].to_dict()

@pytest.fixture(scope='module')
def new_run():
    raw=raw_example();profile=public_profile(raw,dict(requested_amount=600000,requested_months=36,requested_purpose='设备购置',decision_engine='enterprise-v3'))
    return DiligenceRun(raw,profile,'融资组合','三年虚构测试').local()

def test_shared_required_contract_and_optional_notes():
    rows=history_template_rows(True);assert len(REQUIRED)==34
    assert not any('链接' in row[1] for row in rows)
    required=[r for r in rows[5:] if '可选' not in r[0]];assert len(required)==34
    assert all(isinstance(v,(int,float)) for r in required for v in r[2:])
    raw=raw_example();assert raw['input_contract']==CONTRACT and completeness(raw)['complete']
    for obs in raw['financial_history']:
        for key in list(obs['values']):
            if key not in REQUIRED:obs['values'].pop(key)
    assert completeness(raw)['complete']
    raw['financial_history'][0]['values']['inventory']=None
    q=completeness(raw);assert q['template_required'] and len(q['missing'])==1
    assert not public_model(raw,{'requested_amount':600000})['available']

def test_blank_year_not_silently_dropped():
    rows=history_template_rows(True)
    for row in rows[5:]:row[2]=''
    raw=parse_public_blocks({'财报':pd.DataFrame(rows)}).iloc[0].to_dict()
    assert len(raw['financial_history'])==3
    assert len(completeness(raw)['missing'])==len(REQUIRED)

def test_rolling_dates_and_dynamic_excel(monkeypatch):
    import finbridge.data_contract as dc
    monkeypatch.setattr(dc,'china_today',lambda:date(2031,2,5))
    assert rolling_years()==[2028,2029,2030]
    assert history_template_rows()[0][2:]==['2028年度','2029年度','2030年度']
    wb=pd.read_excel(io.BytesIO(history_template_xlsx(False)),header=None)
    assert wb.iloc[0,2:].tolist()==['2028年度','2029年度','2030年度']
    with pytest.raises(ValueError):rolling_years(2031)

def test_diagnostic_cash_flows_enter_optimizer_and_fixed_plan_risk(new_run):
    assert new_run['status']=='已完成'
    p=new_run['outputs']['optimize_financing_portfolio'];d=new_run['financial_analysis']['diagnostics'];s=d['support']
    assert len(s['scenarios'])==5 and s['conservative_ocf']==min(x['ocf'] for x in s['scenarios'])
    margin=next(x for x in s['scenarios'] if x['id']=='margin');turn=next(x for x in s['scenarios'] if x['id']=='turnover')
    assert margin['gross_margin_cash_loss']>0 and margin['ocf']<s['base_ocf']
    assert turn['nwc_increase']>s['scenarios'][0]['nwc_increase']
    m=p['model'];drop=p['algorithm']['planning_stress']['cash_drop']
    assert m['cash']-abs(m['cash'])*drop<=m['conservative_cash']+.1
    risk=p['risk_evaluation'];assert len(risk['dimensions'])==6 and len(risk['diagnostic_stress'])==5
    assert [x['samples'] for x in risk['sample_stability']]==[1000,2000,3000]
    assert risk['frequency_sampling_range']['lower']<=risk['cash_shortfall_probability']<=risk['frequency_sampling_range']['upper']
    for case in risk['diagnostic_stress']:
        assert case['gap_to_target']==pytest.approx(max(0,m['assumptions']['target_coverage']*risk['peak_service']-case['annual_cash']))
    assert new_run['outputs']['verify_decision']['passed']
    tampered=deepcopy(p);tampered['model']['cash']+=1e7
    assert not verify_plan(tampered)['passed']

def test_fixed_asset_pool_does_not_include_other_noncurrent_assets():
    raw=public_example();raw['fixed_assets']=200000
    profile=dict(requested_amount=600000,requested_months=36,requested_purpose='设备购置')
    model=public_model(raw,profile);rules={p['id']:p for p in product_rules(raw,profile,model)}
    assert rules['secured']['capacity']==0 and rules['leasing']['capacity']==160000

def source_handler(years,missing_income=False,future_notice=False):
    def handle(request):
        if 'topSearch' in str(request.url):return httpx.Response(200,json=[dict(code='603288',category='A股',type='shj',orgId='org',zwjc='测试企业')])
        if 'hisAnnouncement' in str(request.url):return httpx.Response(200,json={'announcements':[]})
        kind=request.url.params['reportName'].removeprefix('RPT_F10_FINANCE_');values=raw_example();rows=[]
        for y in years:
            if missing_income and kind=='GINCOME' and y==max(years):continue
            row={field:values.get(k) for k,field in MAPS[kind].items()}
            row.update(REPORT_DATE=f'{y}-12-31',NOTICE_DATE=f'{y+1}-03-20',CURRENCY='CNY')
            if future_notice and y==max(years):row['NOTICE_DATE']='2032-03-20'
            rows.append(row)
        return httpx.Response(200,json={'result':{'data':rows}})
    return handle

def test_retrieval_rolls_and_missing_latest_does_not_hide_with_old_years():
    with httpx.Client(transport=httpx.MockTransport(source_handler([2030,2029,2028],missing_income=True))) as c:
        r=retrieve_a_share('603288','SH','制造业','广东',client=c,as_of=date(2031,10,14))
    q=r['retrieval'];assert q['years']==[2028,2029,2030]
    assert q['template_required'] and 'revenue' in q['missing']['2030']
    assert r['quality'][0]['required_per_year']==34

def test_not_yet_disclosed_report_is_excluded():
    with httpx.Client(transport=httpx.MockTransport(source_handler([2030,2029,2028],future_notice=True))) as c:
        r=retrieve_a_share('603288','SH','制造业','广东',client=c,as_of=date(2031,1,5))
    assert r['retrieval']['years']==[2027,2028,2029]
    assert r['retrieval']['template_required']

class Model:
    def __init__(self,code='603288'):
        self.code=code;self.chat=NS(completions=NS(create=self.create))
    def create(self,**kwargs):
        self.request=kwargs
        call=NS(function=NS(name='fetch_public_annual_statements',arguments=json.dumps({'code':self.code,'market':'SH'})))
        return NS(choices=[NS(message=NS(tool_calls=[call]))])

def test_deepseek_calls_only_verified_tool_and_never_supplies_figures():
    calls=[]
    def fetch(*args):
        calls.append(args)
        return dict(retrieval=dict(as_of='2031-10-14',years=[2028,2029,2030],template_required=True))
    model=Model();result=retrieve_with_agent('603288','SH','制造','广东',Settings('fake','https://example.invalid','test'),model_client=model,retriever=fetch)
    assert result['retrieval']['agent']['model_used'] and len(calls)==1
    assert model.request['tool_choice']['function']['name']=='fetch_public_annual_statements'
    bad=Model('600000');result=retrieve_with_agent('603288','SH','制造','广东',Settings('fake','https://example.invalid','test'),model_client=bad,retriever=fetch)
    assert not result['retrieval']['agent']['model_used'] and calls[-1][0]=='603288'

def test_cash_sensitivity_is_temporary_and_does_not_rewrite_history(new_run):
    from finbridge.decision_chat import DecisionConversation
    agent=DecisionConversation(new_run,Settings('fake','https://example.invalid','test'))
    before=deepcopy(new_run['raw_public'])
    result=agent.execute('simulate_scenario',dict(changes={},financial_change=dict(field='operating_cash_flow',operation='decrease_percent',value=10)), '如果经营现金流下降10%，试算一下')
    assert result and new_run['raw_public']==before

def test_method_publication_years_are_not_rejected_as_financial_guesses(new_run):
    from finbridge.decision_chat import validate_grounded_numbers
    validate_grounded_numbers('参考2001年的结构分析与1953年的归因方法；尾部风险方法发表于2000年。',new_run,new_run)
    with pytest.raises(ValueError):validate_grounded_numbers('该企业1905年融资。',new_run,new_run)

def test_api_blocks_any_missing_required_annual_field(tmp_path):
    from starlette.testclient import TestClient
    from finbridge.web_api import create_app
    with TestClient(create_app(database_path=tmp_path/'gate.db')) as c:
        c.get('/api/bootstrap');raw=raw_example();raw['financial_history'][0]['values'].pop('selling_expense')
        assert c.post('/api/company',json={'data':raw}).status_code==200
        response=c.post('/api/runs',json={'profile':{'requested_amount':600000,'requested_months':12,'requested_purpose':'经营周转'},'use_ai':False})
        assert response.status_code==400 and '模板' in response.json()['error']
        assert not c.get('/api/bootstrap').json()['active_run_id']
