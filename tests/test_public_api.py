import time
from copy import deepcopy
import pytest
from starlette.testclient import TestClient
from finbridge.web_api import create_app
from finbridge.public_data import public_example
from finbridge.public_template import public_template_xlsx


@pytest.fixture
def public_client(tmp_path,monkeypatch):
    # Retain legacy API regression coverage; production one-year scope is tested
    # in test_working_capital_year without this compatibility fixture.
    import finbridge.working_capital_year as annual
    monkeypatch.setattr(annual,'year_profile',lambda profile=None:dict(profile or {}))
    with TestClient(create_app(database_path=tmp_path/'public.sqlite3')) as client:
        b=client.get('/api/bootstrap').json()
        # Keep these legacy contract tests independent of the sourced live demo.
        data={**public_example(),'operating_cash_flow':2800000,'prior_operating_cash_flow':2400000}
        assert client.post('/api/company',json={'data':data,'profile':{}}).status_code==200
        yield client


def wait_for(client,taskid):
    for _ in range(3000):
        result=client.get('/api/runs/'+taskid).json()
        if result['status']!='执行中':
            assert result['status']=='已完成',result
            return result
        time.sleep(.01)
    raise AssertionError('Public task did not complete')


def test_public_default_and_templates_do_not_request_private_financial_inputs(public_client):
    b=public_client.get('/api/bootstrap').json()
    assert b['data']['statement_schema']=='public-v2'
    assert 'confirmed_credit_limit' not in b['fields']
    assert 'cash_flow_available_for_debt_service' not in b['fields']
    assert b['public_model']['available']
    assert public_client.get('/public.js').status_code==200
    upload=public_client.post('/api/upload',files={'file':('公开.xlsx',public_template_xlsx(True))})
    assert upload.status_code==200,upload.text
    row=upload.json()['records'][0]
    assert row['public_provenance']['revenue']['cell'].startswith('C')


@pytest.mark.parametrize('goal',['融资组合','风险分析','方案比较'])
def test_public_task_report_and_revision_preserve_original_facts(public_client,goal):
    client=public_client
    b=client.get('/api/bootstrap').json()
    created=client.post('/api/runs',json={'goal':goal,'profile':{},'use_ai':False})
    assert created.status_code==202,created.text
    run=wait_for(client,created.json()['id'])
    assert len(run['events'])==10 and run['outputs']['verify_decision']['passed']
    assert run['decision_engine']=='enterprise-v3'
    report=client.get('/api/runs/'+run['id']+'/download?format=markdown')
    assert report.status_code==200 and '企业财务与融资决策报告' in report.text
    revision=client.post('/api/runs/'+run['id']+'/revision',json={'assumptions':{'requested_amount':250000.}})
    assert revision.status_code==202,revision.text
    revised=wait_for(client,revision.json()['id'])
    assert revised['parent_run_id']==run['id']
    assert revised['raw_public']==run['raw_public']
    assert revised['revision_delta']['gap']==150000.
    assert client.get('/api/runs/'+run['id']).json()['outputs']==run['outputs']


def test_public_api_rejects_internal_inputs_and_out_of_range_settings(public_client):
    client=public_client;b=client.get('/api/bootstrap').json()
    poisoned=dict(b['data'],confirmed_credit_limit=1e9)
    assert client.post('/api/company',json={'data':poisoned}).status_code==400
    assert client.post('/api/runs',json={'profile':{'amount':1e6}}).status_code==400
    assert client.post('/api/runs',json={'profile':{'forecast_growth':20}}).status_code==400
    run=wait_for(client,client.post('/api/runs',json={}).json()['id'])
    assert client.post('/api/runs/'+run['id']+'/adjustment',json={'changes':{'confirmed_credit_limit':1e9}}).status_code==400
    assert client.post('/api/runs/'+run['id']+'/simulate',json={'cash_drop':.2}).status_code==400


def test_annual_public_values_missing_do_not_become_feasible_budgets(public_client):
    client=public_client;b=client.get('/api/bootstrap').json()
    data=dict(b['data'],capital_expenditure=None)
    assert client.post('/api/company',json={'data':data,'profile':{}}).status_code==200
    run=wait_for(client,client.post('/api/runs',json={}).json()['id'])
    assert not run['outputs']['optimize_financing_portfolio']['available']
    assert not run['outputs']['verify_decision']['passed']


@pytest.mark.parametrize('goal',['融资组合','风险分析','方案比较'])
def test_enterprise_request_alternative_and_changed_demand_revision(public_client,goal):
    client=public_client
    client.get('/api/bootstrap')
    profile=dict(requested_amount=1_500_000.,requested_months=12,requested_purpose='设备购置',enterprise_type='科创企业')
    created=client.post('/api/runs',json={'goal':goal,'profile':profile})
    assert created.status_code==202,created.text
    run=wait_for(client,created.json()['id'])
    assert len(run['events'])==10
    review=run['outputs']['review_financing_request']
    assert not review['reasonable'] and review['alternative']['verified']
    assert 0<review['alternative']['amount']<profile['requested_amount']
    assert review['alternative']['verification']['passed']
    report=client.get('/api/runs/'+run['id']+'/download?format=markdown')
    assert report.status_code==200 and '融资策略' in report.text and '风险与执行条件' in report.text
    rev=client.post('/api/runs/'+run['id']+'/revision',json={'assumptions':{'requested_amount':600_000.,'requested_months':60}})
    assert rev.status_code==202,rev.text
    revised=wait_for(client,rev.json()['id'])
    assert revised['input_profile']['requested_amount']==600_000.
    assert revised['raw_public']==run['raw_public']
    assert revised['revision_delta']['gap']==-900_000.
    assert client.get('/api/runs/'+run['id']).json()['outputs']==run['outputs']
