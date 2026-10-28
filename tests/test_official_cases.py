"""Source and import validation only: never solve the held-out test companies."""
from pathlib import Path
import io,json
import pandas as pd
from starlette.testclient import TestClient
from finbridge.real_case import real_cases,find_real_case
from finbridge.data_contract import completeness,REQUIRED
from finbridge.deep_diagnostics import historical_issues
from finbridge.public_data import parse_public_blocks
from finbridge.web_api import create_app
from conftest import settle

def test_official_raw_data_and_xlsx_are_identical():
    manifest=json.loads(Path('data/official_cases/workbooks.json').read_text(encoding='utf8'))
    for f in manifest:
        c=json.loads(Path('data/official_cases/'+f['slug']+'.json').read_text(encoding='utf8'))
        d=c['data'];assert completeness(d)['complete'] and not historical_issues(d)
        assert all(s['url'].startswith(('https://static.cninfo.com.cn/','https://www.fuyaogroup.com/')) and len(s['sha256'])==64 for s in c['sources'])
        for r in d['financial_history']:
            assert all(r['provenance'][k]['page'] and r['provenance'][k]['unit']=='元' for k in REQUIRED)
        frames=pd.read_excel(f['output'],sheet_name=None,header=None)
        imported=parse_public_blocks(frames).iloc[0].to_dict()
        for actual,expected in zip(imported['financial_history'],d['financial_history']):
            assert actual['year']==expected['year']
            assert all(actual['values'][k]==expected['values'][k] for k in REQUIRED)

def test_demo_registry_keeps_held_out_companies_out():
    cases=real_cases();assert len(cases)==2
    assert all(c['profile']['requested_amount']==3e8 for c in cases)
    assert {c['data']['security_code'] for c in cases}=={'688111','600377'}
    assert all(find_real_case(c['data']) for c in cases)

def test_workspace_route_case_downloads_wait_for_manual_analysis(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'demo.db')) as client:
        assert client.get('/workspace').status_code==200
        before=client.get('/api/bootstrap').json();assert before['runs']==[]
        assert [c['id'] for c in before['cases']]==['1','2']
        assert before['data']['security_code']=='688111'
        assert client.post('/api/demo',json={'id':'0'}).status_code==400
        for case in ('1','2'):
            b=client.post('/api/demo',json={'id':case}).json()
            assert b['profile']['requested_amount']==3e8 and b['case_context']['sources']
            assert b['active_run_id'] is None
            assert b['runs']==[]
            download=client.get('/api/template?case='+case)
            assert download.status_code==200
            imported=parse_public_blocks(pd.read_excel(io.BytesIO(download.content),sheet_name=None,header=None)).iloc[0].to_dict()
            assert imported['company_name']==b['data']['company_name']
        runs=client.get('/api/bootstrap').json()['runs']
        assert runs==[]
        for case in ('fuyao','ctg'):
            r=client.get('/api/template?test_case='+case);assert r.status_code==200
            raw=parse_public_blocks(pd.read_excel(io.BytesIO(r.content),sheet_name=None,header=None)).iloc[0].to_dict()
            assert completeness(raw)['complete']


def test_case_reload_preserves_history_and_manual_amount(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'manual.db')) as client:
        b=client.post('/api/demo',json={'id':'1'}).json()
        profile={**b['profile'],'requested_amount':2e8}
        created=client.post('/api/runs',json={'profile':profile,'use_ai':False})
        assert created.status_code==202
        run=settle(client,created.json()['id'])
        assert run['input_profile']['requested_amount']==2e8
        for case in ('1','2','1'):
            loaded=client.post('/api/demo',json={'id':case})
            assert loaded.status_code==200
            state=loaded.json()
            assert state['active_run_id'] is None
            assert len(state['runs'])==1 and state['runs'][0]['id']==run['id']
            assert client.get('/api/runs/'+run['id']).json()['input_profile']['requested_amount']==2e8
