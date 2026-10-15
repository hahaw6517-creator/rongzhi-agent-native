from copy import deepcopy
import pytest
from finbridge.real_case import real_case
from finbridge.workflow import DiligenceRun
from finbridge.decision_chat import DecisionConversation
from finbridge.dialogue_edits import resolve_edits
from finbridge.conversation_context import update_memory
from finbridge.enterprise_model import optimize_financing
from test_decision_chat import ScriptedClient,SETTINGS

@pytest.fixture(scope='module')
def run():
    c=real_case()
    return DiligenceRun(c['data'],c['profile'],'融资组合','对话测试').local()

def edit(key,value,unit,quote,op='set'):
    return dict(parameter=key,operation=op,value=value,unit=unit,evidence=quote)

def test_credit_rate_relative_adjustment_is_isolated(run):
    q='把信用贷款利率增加1个百分点'
    client=ScriptedClient([[('explore_financing',dict(edits=[edit('credit_rate',1,'percentage_points',q,'add')]))]])
    before=deepcopy(run);out=DecisionConversation(run,SETTINGS,client=client).respond(q)
    s=out['scenarios'][0];p=s['snapshot']['outputs']['optimize_financing_portfolio']
    rows={c['id']:c for c in p['composition']}
    assert rows['credit']['rate']==pytest.approx(.05)
    assert rows['secured']['rate']==pytest.approx(.035) and rows['factoring']['rate']==pytest.approx(.048)
    assert p['verification']['passed'] and run==before and out['candidate'] is None
    assert not out['assistant']['pending_update']
    assert s['parameter_items'][0]['before']==pytest.approx(.04)

def test_missing_unit_is_clarified_and_followup_is_remembered(run):
    first=DecisionConversation(run,SETTINGS,client=object()).respond('融资需求为1000000000')
    assert first['assistant']['clarification'] and not first['scenarios']
    memory=update_memory({},first['user'],first['assistant'])
    q='融资需求为1000000000\n用户补充：元'
    client=ScriptedClient([[('explore_financing',dict(edits=[edit('requested_amount',1000000000,'yuan',q)]))]])
    second=DecisionConversation(run,SETTINGS,memory=memory,client=client).respond('元')
    assert second['scenarios'][0]['changes']['requested_amount']==1e9
    assert second['user']['content']=='元' and not second['assistant']['clarification']
    assert 'clarification' not in update_memory(memory,second['user'],second['assistant'])

@pytest.mark.parametrize('q',['融资需求为10亿元','我想借10亿元试试','融资需求改到10亿元'])
def test_natural_amount_changes_become_temporary_scenarios(run,q):
    c=ScriptedClient([[('explore_financing',dict(edits=[edit('requested_amount',10,'yi',q)]))]])
    out=DecisionConversation(run,SETTINGS,client=c).respond(q)
    assert out['scenarios'][0]['snapshot']['input_profile']['requested_amount']==1e9
    assert out['candidate'] is None and out['assistant']['capacity_result'] is None

def test_multiple_parameters_and_cvar_recompute_together(run):
    quotes=['净融资需求设为25亿元','信用贷款利率设为5%','抵押贷款利率设为4.2%','CVaR置信水平设为90%','CVaR权重设为0.3','误差修正比例设为25%','回款延迟设为10天']
    edits=[edit('requested_amount',25,'yi',quotes[0]),edit('credit_rate',5,'percent',quotes[1]),edit('secured_rate',4.2,'percent',quotes[2]),edit('cvar_alpha',90,'percent',quotes[3]),edit('cvar_weight',.3,'number',quotes[4]),edit('calibration_share',25,'percent',quotes[5]),edit('receivable_delay_days',10,'days',quotes[6])]
    client=ScriptedClient([[('explore_financing',dict(edits=edits))]])
    out=DecisionConversation(run,SETTINGS,client=client).respond('，'.join(quotes))
    s=out['scenarios'][0];p=s['snapshot']['outputs']['optimize_financing_portfolio'];f=p['funding']
    assert len(s['parameter_items'])==7 and p['verification']['passed']
    assert p['algorithm']['cvar_alpha']==.9 and p['risk_evaluation']['cvar_alpha']==.9
    assert p['algorithm']['objective_value']==pytest.approx(f['total_assumed_interest']+f['fees_due']+.3*p['cvar'],abs=1)
    assert p['annual_context']['delay_days']==10
    assert p['model']['cash_prediction']['future']['calibration_share']==.25

def test_invalid_edit_clarifies_without_partial_execution(run):
    q='需求改为10亿元，信用贷款年利率设为300%'
    client=ScriptedClient([[('explore_financing',dict(edits=[edit('requested_amount',10,'yi','需求改为10亿元'),edit('credit_rate',300,'percent','信用贷款年利率设为300%')]))]])
    out=DecisionConversation(run,SETTINGS,client=client).respond(q)
    assert out['assistant']['clarification'] and '范围' in out['assistant']['content']
    assert not out['scenarios'] and out['candidate'] is None

def test_vague_question_can_ask_clarification_and_cancel(run):
    c=ScriptedClient([[('ask_clarification',{'question':'您希望降低融资成本，还是提高可融资金额？'})]])
    out=DecisionConversation(run,SETTINGS,client=c).respond('帮我调得更好一点')
    memory=update_memory({},out['user'],out['assistant'])
    cancelled=DecisionConversation(run,SETTINGS,memory=memory,client=object()).respond('取消')
    assert cancelled['assistant']['clarification'] is None and not cancelled['scenarios']

def test_relative_changes_and_unit_mismatch_are_checked(run):
    changes,_=resolve_edits([edit('requested_amount',10,'percent','融资需求增加10%','increase_percent')],run,'融资需求增加10%')
    assert changes['requested_amount']==pytest.approx(330000000)
    negative,_=resolve_edits([edit('forecast_growth',-10,'percent','收入增长率设为-10%')],run,'收入增长率设为-10%')
    assert negative['forecast_growth']==-.1
    disabled,_=resolve_edits([edit('secured_limit',0,'yuan','抵押贷款暂时不用')],run,'抵押贷款暂时不用')
    assert disabled['secured_limit']==0
    normalized,_=resolve_edits([edit('requested_amount',10,'yuan','需求10亿元')],run,'需求10亿元')
    assert normalized['requested_amount']==1e9  # user units take precedence over model representation

def test_zero_channel_limit_and_custom_fees_enter_real_solver(run):
    p=optimize_financing(run['raw_public'],{**run['input_profile'],'secured_limit':0,'credit_rate':.06,'credit_fee_rate':.01,'credit_fixed_fee':2000})
    rows={c['id']:c for c in p['composition']}
    assert rows['secured']['amount']==0 and not rows['secured']['enabled']
    assert rows['credit']['fee_rate']==.01 and rows['credit']['fixed_fee']==2000
    assert p['verification']['passed']

def test_api_failure_keeps_request_and_report(run):
    class Offline:
        @property
        def chat(self):raise ConnectionError('network error')
    out=DecisionConversation(run,SETTINGS,client=Offline()).respond('需求改为10亿元')
    assert out['assistant']['clarification'] and '接口' in out['assistant']['content']
    assert not out['scenarios'] and out['candidate'] is None


def test_followup_can_continue_from_previous_temporary_scenario(run):
    q='信用贷款利率增加1个百分点'
    first=DecisionConversation(run,SETTINGS,client=object())
    first.execute('explore_financing',dict(edits=[edit('credit_rate',1,'percentage_points',q,'add')]),q)
    record=first.new_scenarios[0]
    q2='继续在刚才方案基础上，信用贷款利率再增加1个百分点'
    c=ScriptedClient([[('explore_financing',dict(base_scenario_id=record['id'],edits=[edit('credit_rate',1,'percentage_points',q2,'add')]))]])
    out=DecisionConversation(run,SETTINGS,scenarios=[record],client=c).respond(q2)
    assert out['scenarios'][0]['changes']['credit_rate']==pytest.approx(.06)
    assert out['scenarios'][0]['parameter_items'][0]['before']==pytest.approx(.05)


def test_explaining_a_term_during_clarification_does_not_discard_draft(run):
    first=DecisionConversation(run,SETTINGS,client=object()).respond('融资需求为1000000000')
    memory=update_memory({},first['user'],first['assistant'])
    c=ScriptedClient([dict(reply='DSCR是偿债覆盖倍数，用还款现金与本息比较。',metric_keys=[],source_ids=[],follow_up=None)])
    out=DecisionConversation(run,SETTINGS,memory=memory,client=c).respond('DSCR是什么意思')
    assert out['assistant']['clarification']==memory['clarification']
    assert not out['scenarios'] and '用户补充' not in c.requests[0]['messages'][1]['content'].split('"question":')[-1]


def test_web_conversation_remembers_clarification_without_updating_report(tmp_path,monkeypatch):
    from starlette.testclient import TestClient
    import finbridge.web_api as api
    import finbridge.decision_chat as chat
    from test_decision_chat import wait_run
    original=chat.DecisionConversation
    q='融资需求为1000000000\n用户补充：元'
    class Agent(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs,client=ScriptedClient([[('explore_financing',dict(edits=[edit('requested_amount',1000000000,'yuan',q)]))]]))
    monkeypatch.setattr(chat,'DecisionConversation',Agent)
    monkeypatch.setattr(api,'load_settings',lambda:SETTINGS)
    with TestClient(api.create_app(database_path=tmp_path/'dialogue.db')) as client:
        client.get('/api/bootstrap')
        start=client.post('/api/runs',json={'profile':{'requested_amount':300000000},'use_ai':False})
        r=wait_run(client,start.json()['id']);url='/api/runs/'+r['id']+'/conversation'
        first=client.post(url,json={'message':'融资需求为1000000000'})
        assert first.status_code==200 and first.json()['messages'][-1]['clarification']
        second=client.post(url,json={'message':'元'})
        assert second.status_code==200,second.text
        msg=second.json()['messages'][-1]
        assert msg['scenario_previews'][0]['changes']['requested_amount']==1e9
        assert second.json()['head_run_id']==r['id']
        assert client.get('/api/runs/'+r['id']).json()['input_profile']['requested_amount']==300000000
