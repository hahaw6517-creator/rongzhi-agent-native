from copy import deepcopy
import io
import json
from pathlib import Path
import httpx
import pandas as pd
import pytest
from starlette.testclient import TestClient
from finbridge.public_data import parse_public_blocks,public_example,BLOCKS
from finbridge.public_finance import public_model
from finbridge.public_template import history_template_csv,history_template_xlsx
from finbridge.financial_history import annual_records,flatten_history,validate_history
from finbridge.deep_diagnostics import build_diagnostics,historical_issues
from finbridge.enterprise_model import optimize_financing,verify_plan
from finbridge.listed_financials import retrieve_a_share,MAPS
from finbridge.web_api import create_app

def history():
    frame=pd.read_csv(io.BytesIO(history_template_csv(True)),header=None)
    return parse_public_blocks({'企业财务数据':frame}).iloc[0].to_dict()

def test_history_template_roundtrip_and_blank():
    raw=history();assert [r['year'] for r in raw['financial_history']]==[2023,2024,2025]
    assert raw['revenue']==9600000 and raw['prior_revenue']==8640000
    frames=pd.read_excel(io.BytesIO(history_template_xlsx(True)),header=None,sheet_name=None)
    loaded=parse_public_blocks(frames).iloc[0].to_dict()
    assert loaded['financial_history'][0]['values']['revenue']==7680000
    assert 'restricted_cash' in loaded['financial_history'][-1]['values']
    assert not historical_issues(loaded)

def test_attribution_closes_and_changes_not_causes():
    raw=history();raw['financial_history'][0]['values']['net_profit']*=.7
    raw['net_profit']*=1.2
    d=build_diagnostics(raw)
    a=d['roe_attribution'];assert a['change']==pytest.approx(sum(x['value'] for x in a['contributions']))
    assert abs(a['residual'])<1e-12
    assert d['expense_bridge']['change']==pytest.approx(sum(x['value'] for x in d['expense_bridge']['components'])+d['expense_bridge']['residual'])

def test_gaps_never_zero_or_nonconsecutive_growth():
    raw=history();raw['financial_history']=raw['financial_history'][::2]
    raw=flatten_history(raw,raw['financial_history'])
    d=build_diagnostics(raw);assert d['roe_attribution'] is None and d['support'] is None
    assert raw['prior_revenue'] is None
    del raw['financial_history'][0]['values']['accounts_payable']
    assert build_diagnostics(raw)['working_capital'][0]['nwc'] is None

def test_latest_scenario_preserves_prior_observations():
    raw=history();before=deepcopy(raw['financial_history']);raw['revenue']*=1.1
    rows=annual_records(raw);assert rows[-1]['values']['revenue']==raw['revenue']
    assert rows[:-1]==before[:-1] and raw['financial_history']==before
    with pytest.raises(ValueError):validate_history([dict(year=2025,values={'inventory':-1})])
    raw['report_period']='2024年度'
    with pytest.raises(ValueError):annual_records(raw)

def test_cash_checks_missing_and_mismatch():
    raw=history();d=build_diagnostics(raw)
    # The fictional inputs reconcile exactly, rather than forcing a residual to zero.
    assert d['cash_reconciliation'][-1]['reconciliation']==pytest.approx(0)
    raw['net_financing_cash_flow']+=123
    assert build_diagnostics(raw)['cash_reconciliation'][-1]['reconciliation']==pytest.approx(123)
    raw['net_financing_cash_flow']=None
    assert build_diagnostics(raw)['cash_reconciliation'][-1]['reconciliation'] is None

def test_historical_cash_changes_real_optimizer_constraint():
    raw=history();v=raw['financial_history'][1]['values'];old=v['operating_cash_flow'];v['operating_cash_flow']=500000;v['net_financing_cash_flow']+=old-500000
    profile=dict(requested_amount=600000,requested_months=36,requested_purpose='设备购置')
    model=public_model(raw,profile);assert model['available']
    assert model['conservative_cash']<model['cash']*.8
    plan=optimize_financing(raw,profile)
    expected=1-model['conservative_cash']/model['cash']
    assert plan['algorithm']['planning_stress']['cash_drop']==pytest.approx(expected)
    assert verify_plan(plan)['passed']==plan['verification']['passed']
    assert plan['funding']['net_proceeds']+plan['funding']['unfunded_gap']==pytest.approx(600000,abs=.2)

def test_history_api_preview_and_confirm(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'test.db')) as c:
        before=c.get('/api/bootstrap').json()['data']
        t=c.get('/api/template?example=1');assert t.status_code==200
        reply=c.post('/api/upload',files={'file':('three.xlsx',t.content)})
        assert reply.status_code==200;raw=reply.json()['records'][0]
        assert c.get('/api/bootstrap').json()['data']==before
        assert c.post('/api/company',json={'data':raw}).status_code==200
        assert len(c.get('/api/bootstrap').json()['data']['financial_history'])==3

def mock_source(request):
    if 'topSearch' in str(request.url):return httpx.Response(200,json=[dict(code='603288',category='A股',type='shj',orgId='org',zwjc='测试上市公司')])
    if 'hisAnnouncement' in str(request.url):return httpx.Response(200,json={'announcements':[dict(announcementTitle='2025年年度报告',adjunctUrl='finalpage/2026-03-27/test.PDF'),dict(announcementTitle='2025年年度报告摘要',adjunctUrl='finalpage/a.PDF')]})
    kind=request.url.params['reportName'].removeprefix('RPT_F10_FINANCE_');example=public_example()
    rows=[]
    for year in [2025,2024,2023]:
        row={field:example.get(key) for key,field in MAPS[kind].items()}
        row.update(REPORT_DATE=f'{year}-12-31',CURRENCY='CNY',NOTICE_DATE=f'{year+1}-03-20');rows.append(row)
    rows.append(dict(REPORT_DATE='2026-06-30',CURRENCY='CNY',OPERATE_INCOME=999))
    return httpx.Response(200,json={'result':{'data':rows}})

def test_listed_identity_annual_and_null_rules():
    with httpx.Client(transport=httpx.MockTransport(mock_source)) as c:
        result=retrieve_a_share('603288','SH',client=c)
        assert result['retrieval']['years']==[2023,2024,2025]
        assert len(result['retrieval']['official_reports'])==1
        assert '待' in result['records'][0]['public_provenance']['revenue']['verification']
        assert 'restricted_cash' not in result['records'][0]
        with pytest.raises(ValueError):retrieve_a_share('603288','SZ',client=c)
        with pytest.raises(ValueError):retrieve_a_share('bad','SH',client=c)
