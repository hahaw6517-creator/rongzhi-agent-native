from copy import deepcopy
import pytest
from finbridge.decision_chat import DecisionConversation,confirm_proposal,validate_grounded_numbers
from finbridge.public_data import public_example
from finbridge.public_finance import public_profile
from finbridge.workflow import DiligenceRun
from finbridge.config import Settings
from finbridge.conversation_context import knowledge_for,update_memory

SETTINGS=Settings('test','https://example.invalid','test')

@pytest.fixture(scope='module')
def run():
    raw=public_example();raw.update(operating_cash_flow=2800000,prior_operating_cash_flow=2400000)
    profile=public_profile(raw,dict(decision_engine='enterprise-v3',requested_amount=600000,requested_months=36,requested_purpose='设备购置'))
    return DiligenceRun(raw,profile,'融资组合','测试').local()

def test_scenario_isolated_and_can_only_be_adopted_after_confirmation(run):
    before=deepcopy(run);agent=DecisionConversation(run,SETTINGS,client=object())
    preview=agent.execute('simulate_scenario',dict(changes=dict(requested_amount=800000),strategy='cost_only'),'如果融资需求改成80万元，成本优先试算')
    assert run==before and agent.candidate is None and agent.current['id']==run['id']
    record=agent.new_scenarios[0]
    assert preview['temporary'] and record['snapshot']['outputs']['optimize_financing_portfolio']['strategy']=='成本优先'
    restored=DecisionConversation(run,SETTINGS,scenarios=[record],client=object())
    proposal=restored.execute('propose_scenario_adjustment',{},'采用刚才的情景')['proposal']
    assert restored.candidate is None
    updated=confirm_proposal(run,proposal,True,SETTINGS)['candidate']
    assert updated['input_profile']['requested_amount']==800000
    assert updated['input_profile']['optimization_strategy']=='cost_only'

def test_financial_hypothesis_does_not_become_historical_truth(run):
    agent=DecisionConversation(run,SETTINGS,client=object())
    agent.execute('simulate_scenario',dict(changes={},financial_change=dict(field='operating_cash_flow',operation='decrease_percent',value=10)),'如果经营现金流下降10%，试算一下')
    record=agent.new_scenarios[0]
    assert record['snapshot']['raw_public']['operating_cash_flow']==2520000
    assert agent.current['raw_public']['operating_cash_flow']==2800000 and agent.candidate is None
    restored=DecisionConversation(run,SETTINGS,scenarios=[record],client=object())
    with pytest.raises(ValueError,match='真实财报'):restored.execute('propose_scenario_adjustment',{},'采用刚才的情景')

def test_unrequested_financial_assumptions_rejected(run):
    agent=DecisionConversation(run,SETTINGS,client=object())
    with pytest.raises(ValueError):agent.execute('simulate_scenario',dict(changes={},financial_change=dict(field='operating_cash_flow',operation='decrease_percent',value=20)),'如果经营现金流下降10%，试算一下')
    assert agent.candidate is None and not agent.new_scenarios

def test_capacity_not_limited_by_requested_amount(run):
    agent=DecisionConversation(run,SETTINGS,client=object())
    result=agent.execute('estimate_financing_capacity',dict(compare_terms=False),'融资金额太少，测算融资边界')
    assert result['primary']['verified'] and result['primary']['net_capacity']>600000
    assert agent.candidate is None and agent.current['input_profile']['requested_amount']==600000

def test_knowledge_and_memory_are_separate_from_company_facts():
    assert knowledge_for('现金流预测')[0]['id']=='FIN-CASH'
    memory=update_memory({},dict(content='只说重点'),dict(response_mode='解释',scenario_previews=[dict(id='test')]))
    assert memory['preferences']['answer_style'] and memory['last_scenario_ids']==['test']
    assert 'raw_public' not in memory

def test_direct_explanation_receives_context_without_forced_tool(run):
    from test_decision_chat import ScriptedClient
    import json
    client=ScriptedClient([dict(reply='本次预测采用财报现金流和列明的投资假设，不是对未来回款的保证。',metric_keys=[],source_ids=[],follow_up=None)])
    result=DecisionConversation(run,SETTINGS,client=client).respond('解释一下现金流预测方法')
    assert result['candidate'] is None and not result['assistant']['pending_update']
    assert result['assistant']['model_text_validated']
    request=client.requests[0]
    assert request['tool_choice']=='auto'
    payload=json.loads(request['messages'][1]['content'])
    assert payload['raw_financial_data']==run['raw_public'] and payload['calculated_metrics']
    assert payload['professional_knowledge']

def test_fenced_model_json_and_explaining_existing_scenario_are_read_only(run):
    from types import SimpleNamespace
    import json
    from test_decision_chat import ScriptedClient
    class FencedClient(ScriptedClient):
        def create(self,**kwargs):
            response=super().create(**kwargs)
            response.choices[0].message.content='```json\n'+response.choices[0].message.content+'\n```'
            return response
    client=FencedClient([dict(reply='临时情景用于比较，正式报告保持原条件。',metric_keys=[],source_ids=[],follow_up=None)])
    result=DecisionConversation(run,SETTINGS,client=client).respond('刚才的情景与正式报告有什么不同？')
    assert result['assistant']['model_text_validated'] and result['candidate'] is None
    assert not result['assistant']['tools']

def test_stale_scenarios_do_not_enter_new_request_context(run):
    agent=DecisionConversation(run,SETTINGS,client=object())
    agent.execute('simulate_scenario',dict(changes=dict(requested_amount=800000)),'如果融资需求改成80万元，试算一下')
    updated=deepcopy(run);updated['input_profile']['requested_amount']=900000
    restored=DecisionConversation(updated,SETTINGS,scenarios=agent.new_scenarios,client=object())
    assert not restored.scenarios

def test_followup_scenario_inherits_previous_assumptions_without_changing_report(run):
    first=DecisionConversation(run,SETTINGS,client=object())
    first.execute('simulate_scenario',dict(changes=dict(requested_amount=800000)),'如果融资需求改成80万元，试算一下')
    record=first.new_scenarios[0]
    follow=DecisionConversation(run,SETTINGS,scenarios=[record],client=object())
    result=follow.execute('simulate_scenario',dict(changes={},strategy='repayment',base_scenario_id=record['id']),'在刚才的情景上再保守一点')
    latest=follow.new_scenarios[-1]
    assert latest['snapshot']['input_profile']['requested_amount']==800000
    assert latest['snapshot']['outputs']['optimize_financing_portfolio']['strategy']=='风险优先'
    assert follow.current['input_profile']['requested_amount']==600000 and follow.candidate is None
    assert result['base_scenario_id']==record['id']

def test_explanation_preserves_pending_confirmation(tmp_path,run):
    import finbridge.web_api as api
    store=api.SessionStore(tmp_path/'pending.sqlite3')
    token,state,_=store.session(None)
    store.update(token,data=run['raw_public'],profile=run['input_profile'],active_run_id=run['id'])
    chat=store.conversation(token,run)
    pending=dict(id='pending',parent_run_id=run['id'],changes=dict(requested_amount=800000))
    store.save_conversation(token,chat,run,dict(user=dict(role='user',content='改成80万元'),assistant=dict(role='assistant',content='请确认',tools=[],pending_update=pending),candidate=None))
    chat=store.conversation(token,run)
    result=store.save_conversation(token,chat,run,dict(user=dict(role='user',content='为什么这么改'),assistant=dict(role='assistant',content='解释调整依据',tools=[]),candidate=None))
    assert result['messages'][-1]['pending_update']==pending
    assert result['messages'][-1]['content']=='解释调整依据'

def test_workspace_persists_scenario_and_company_switch_clears_active_context(tmp_path,monkeypatch):
    import finbridge.working_capital_year as annual
    monkeypatch.setattr(annual,'year_profile',lambda profile=None:dict(profile or {}))
    import finbridge.web_api as api
    import finbridge.decision_chat as chat_module
    from test_decision_chat import ScriptedClient,wait_run
    from starlette.testclient import TestClient
    class FakeAgent(DecisionConversation):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs,client=ScriptedClient([[('simulate_scenario',dict(changes=dict(requested_amount=800000)))],dict(reply='临时试算已完成，原报告保留。',metric_keys=[],source_ids=[],follow_up=None)]))
    monkeypatch.setattr(chat_module,'DecisionConversation',FakeAgent)
    monkeypatch.setattr(api,'load_settings',lambda:SETTINGS)
    with TestClient(api.create_app(database_path=tmp_path/'workspace.sqlite3')) as client:
        boot=client.get('/api/bootstrap').json()
        profile={**boot['profile'], 'requested_amount':600000,'requested_months':36,'requested_purpose':'设备购置','decision_engine':'enterprise-v3'}
        run=wait_run(client,client.post('/api/runs',json=dict(profile=profile)).json()['id'])
        path='/api/runs/'+run['id']+'/conversation'
        result=client.post(path,json=dict(message='只说重点，如果融资需求改成80万元，试算一下'))
        assert result.status_code==200,result.text
        assert not result.json()['saved_version']
        reloaded=client.get(path).json()
        assert reloaded['memory']['preferences']['answer_style']
        assert reloaded['messages'][-1]['scenario_previews']
        assert 'scenarios' not in reloaded
        changed={**boot['data'],'company_name':'另一家企业'}
        response=client.post('/api/company',json=dict(data=changed,profile=profile))
        assert response.status_code==200,response.text
        assert response.json()['active_run_id'] is None
        assert response.json()['profile'].get('requested_amount')!=600000
        assert client.post(path,json=dict(message='解释旧企业')).status_code==409
