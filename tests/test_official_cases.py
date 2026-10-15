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
    cases=real_cases();assert len(cases)==3
    assert all(c['profile']['requested_amount']==3e8 for c in cases)
    assert {c['data']['security_code'] for c in cases}=={'603288','688111','600377'}
    assert all(find_real_case(c['data']) for c in cases)

def test_workspace_route_case_downloads_and_no_automatic_runs(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'demo.db')) as client:
        assert client.get('/workspace').status_code==200
        before=client.get('/api/bootstrap').json();assert before['runs']==[]
        for case in ('1','2'):
            b=client.post('/api/demo',json={'id':case}).json()
            assert b['profile']['requested_amount']==3e8 and b['case_context']['sources']
            assert client.get('/api/template?case='+case).status_code==200
        for case in ('fuyao','ctg'):
            r=client.get('/api/template?test_case='+case);assert r.status_code==200
            raw=parse_public_blocks(pd.read_excel(io.BytesIO(r.content),sheet_name=None,header=None)).iloc[0].to_dict()
            assert completeness(raw)['complete']
        assert client.get('/api/bootstrap').json()['runs']==[]
