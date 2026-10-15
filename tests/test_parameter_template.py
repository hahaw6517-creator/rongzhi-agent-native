from copy import deepcopy
import json
import pytest
from finbridge.parameter_template import definitions,template_text,parse_template
from finbridge.decision_chat import DecisionConversation
from finbridge.real_case import real_case
from finbridge.workflow import DiligenceRun
from test_decision_chat import ScriptedClient,SETTINGS

@pytest.fixture(scope='module')
def run():
    c=real_case();return DiligenceRun(c['data'],c['profile'],'融资组合','参数模板测试').local()

def test_all_thirty_fields_and_blank_rows(run):
    assert len(definitions())==30
    text=template_text().replace('净融资需求（亿元）=','净融资需求（亿元）=5').replace('信用贷款年利率（%）=','信用贷款年利率（%）=5')
    p=parse_template(text,run)
    assert p['changes']=={'requested_amount':500000000,'credit_rate':.05}
    assert parse_template('为什么推荐这个方案？',run) is None

def test_batch_template_bypasses_stale_clarification_and_model_unit_conversion(run):
    q='[参数调整]\n净融资需求（亿元）=5\n信用贷款年利率（%）=5\n抵押贷款本金上限（亿元）=2\n偿债覆盖安全线（倍）=1.5'
    memory={'clarification':{'draft_question':'旧问题反复确认500000亿元','fingerprint':run['fingerprint']}}
    client=ScriptedClient([[('recalculate_template',{})]])
    before=deepcopy(run);out=DecisionConversation(run,SETTINGS,memory=memory,client=client).respond(q)
    assert run==before and out['candidate'] is None
    s=out['scenarios'][0]
    assert s['changes']==dict(requested_amount=5e8,credit_rate=.05,secured_limit=2e8,target_coverage=1.5)
    assert s['snapshot']['outputs']['verify_decision']['passed']
    assert len(s['parameter_items'])==4
    request=client.requests[0]
    assert request['tool_choice']['function']['name']=='recalculate_template'
    assert [t['function']['name'] for t in request['tools']]==['recalculate_template']
    assert not out['assistant']['clarification']

@pytest.mark.parametrize('text,reason',[
 ('[参数调整]\n净融资需求（亿元）=','至少填写'),
 ('[参数调整]\n信用贷款年利率（%）=300','支持范围'),
 ('[参数调整]\n净融资需求（元）=5','名称或单位'),
 ('[参数调整]\n信用贷款年利率（%）=增加1个百分点','填写数值'),
 ('[参数调整]\n净融资需求（亿元）=5\n净融资需求（亿元）=2','两次'),
])
def test_invalid_template_gives_specific_feedback_without_model_loop(run,text,reason):
    out=DecisionConversation(run,SETTINGS,client=object()).respond(text)
    assert reason in out['assistant']['content']
    assert not out['scenarios'] and not out['assistant']['clarification']

def test_template_metadata_matches_browser_source():
    from pathlib import Path
    src=Path('web/parameter-template.js').read_text(encoding='utf-8')
    assert json.dumps(definitions(),ensure_ascii=False) in src

def test_many_independent_overrides_are_applied_together(run):
    q='[参数调整]\n净融资需求（亿元）=5\n信用贷款年利率（%）=5\n抵押贷款年利率（%）=4.2\n抵押贷款本金上限（亿元）=2\nCVaR权重（数值）=0.3\nCVaR置信水平（%）=90\n压力回款延迟天数（天）=10\n预测误差修正比例（%）=25'
    out=DecisionConversation(run,SETTINGS,client=ScriptedClient([[('recalculate_template',{})]])).respond(q)
    assert len(out['scenarios'][0]['changes'])==8
    p=out['scenarios'][0]['snapshot']['outputs']['optimize_financing_portfolio']
    assert p['algorithm']['cvar_alpha']==.9 and p['verification']['passed']
    assert p['annual_context']['delay_days']==10
