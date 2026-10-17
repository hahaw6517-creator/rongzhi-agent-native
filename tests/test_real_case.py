"""The public case must stay complete, sourced and separate from its request."""
import io
import pandas as pd
from starlette.testclient import TestClient
from finbridge.data_contract import REQUIRED,completeness
from finbridge.deep_diagnostics import historical_issues
from finbridge.public_data import parse_public_blocks
from finbridge.real_case import real_case
from finbridge.web_api import create_app
from finbridge.public_finance import public_profile
from finbridge.workflow import DiligenceRun
from conftest import settle


def test_official_case_preserves_three_years_and_restatement():
    c=real_case();d=c['data'];rows=d['financial_history']
    assert [r['year'] for r in rows]==[2023,2024,2025]
    assert completeness(d)['complete'] and not historical_issues(d)
    assert all(set(REQUIRED)<=set(r['values']) for r in rows)
    assert all(set(r['values'])==set(r['provenance']) for r in rows)
    assert d['prior_revenue']==26904508894.01
    assert d['prior_operating_cash_flow']==6840201569.11
    assert d['net_profit']==7045452349.14
    assert d['long_term_debt']==0 and d['advance_receipts']==0
    assert '重述' in c['notes'][0] and '未据此自行追溯重编' in c['notes'][0]
    assert 'requested_amount' not in d
    c['data']['revenue']=0
    assert real_case()['data']['revenue']>0


def test_case_load_and_download_share_the_same_financial_values(tmp_path):
    with TestClient(create_app(database_path=tmp_path/'case.sqlite3')) as client:
        b=client.get('/api/bootstrap').json()
        assert len(b['cases'])==3 and b['source'].startswith('真实算例')
        assert len(b['data']['financial_history'])==3
        assert b['profile']['requested_amount']==300000000
        assert b['profile']['requested_months']==12
        assert b['profile']['requested_purpose']=='经营周转'
        assert '测试假设' in b['profile']['objective']
        assert b['public_model']['available'] and b['case_context']['sources']
        client.post('/api/company',json={'data':b['data'],'profile':{'requested_amount':1e7,'requested_months':12}})
        reloaded=client.post('/api/demo',json={'id':'0'}).json()
        assert reloaded['profile']['requested_amount']==3e8
        assert reloaded['profile']['requested_months']==12
        # 案例载入自动生成历史分析任务
        settle(client,reloaded['active_run_id'])
        assert client.post('/api/demo',json={'id':'3'}).status_code==400
        for mode in ('xlsx','csv'):
            reply=client.get('/api/template?real=1'+('&format=csv' if mode=='csv' else ''))
            assert reply.status_code==200
            frames=pd.read_excel(io.BytesIO(reply.content),sheet_name=None,header=None) if mode=='xlsx' else {'财报':pd.read_csv(io.BytesIO(reply.content),header=None)}
            raw=parse_public_blocks(frames).iloc[0].to_dict()
            assert completeness(raw)['complete'] and not historical_issues(raw)
            assert [r['values'] for r in raw['financial_history']]==[r['values'] for r in b['data']['financial_history']]


def test_repeated_demo_load_replaces_previous_auto_run(tmp_path):
    """同一案例重复载入：未复核的旧同输入自动分析被替换，历史分析保持每案例一份；已复核的保留不替换。"""
    with TestClient(create_app(database_path=tmp_path/'dedup.sqlite3')) as client:
        first=client.post('/api/demo',json={'id':'0'}).json()
        settle(client,first['active_run_id'])
        second=client.post('/api/demo',json={'id':'0'}).json()
        settle(client,second['active_run_id'])
        ids=[r['id'] for r in client.get('/api/bootstrap').json()['runs']]
        assert ids==[second['active_run_id']], '重复载入同案例应只保留最新一条自动分析'
        # 已复核的分析视为正式资产：再次载入不替换，旧记录与新自动分析并存
        assert client.patch('/api/runs/'+second['active_run_id'],json={'reviewed':True}).status_code==200
        third=client.post('/api/demo',json={'id':'0'}).json()
        settle(client,third['active_run_id'])
        ids=[r['id'] for r in client.get('/api/bootstrap').json()['runs']]
        assert set(ids)=={second['active_run_id'],third['active_run_id']}, '已复核记录不应被重复载入替换'


def test_real_case_request_passes_the_existing_python_workflow():
    c=real_case();r=DiligenceRun(c['data'],public_profile(c['data'],c['profile']),'融资组合','真实算例测试').local()
    assert r['status']=='已完成'
    assert r['outputs']['verify_decision']['passed']
    plan=r['outputs']['optimize_financing_portfolio']
    assert plan['funding']['net_proceeds']>=3e8-.10001
    assert plan['funding']['unfunded_gap']<=.10001  # solver tolerance + float roundoff
    assert len(r['outputs']['assess_risk']['enterprise_risk']['diagnostic_stress'])>=6
