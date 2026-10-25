from copy import deepcopy
import json
import pytest
from finbridge.parameter_template import definitions,template_text,parse_template,current_values
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


def prefilled(run,changes=None):
    values={**current_values(run),**(changes or {})}
    lines=['[参数调整]']
    for d in definitions():
        scale=1e8 if d['kind']=='money' else .01 if d['kind']=='percent' else 1
        lines.append(f"{d['label']}（{d['unit']}）={values[d['key']]/scale:.12f}")
    return '\n'.join(lines)


def test_prefilled_template_uses_actual_forecast_and_channel_defaults(run):
    values=current_values(run)
    assert len(values)==30 and all(v is not None for v in values.values())
    assert values['forecast_growth']==run['financial_analysis']['forecast']['history_prediction']['future']['growth']
    for c in run['outputs']['optimize_financing_portfolio']['composition']:
        if c['id']=='leasing':continue
        assert values[c['id']+'_rate']==c['rate']
        assert values[c['id']+'_limit']==c['capacity']
    with pytest.raises(ValueError,match='与当前方案一致'):
        parse_template(prefilled(run),run)


def test_prefilled_batch_only_changes_edited_values_and_recalculates_caps(run):
    changes=dict(requested_amount=5e8,assumed_rate=.06,cvar_weight=.3)
    question=prefilled(run,changes)
    before=deepcopy(run)
    out=DecisionConversation(run,SETTINGS,client=ScriptedClient([[('recalculate_template',{})]])).respond(question)
    assert run==before
    scenario=out['scenarios'][0]
    assert scenario['changes']==pytest.approx(changes)
    assert len(scenario['parameter_items'])==3
    new=scenario['snapshot']['outputs']['optimize_financing_portfolio']
    assert new['verification']['passed']
    credit=next(c for c in new['composition'] if c['id']=='credit')
    old=next(c for c in run['outputs']['optimize_financing_portfolio']['composition'] if c['id']=='credit')
    assert credit['rate']==pytest.approx(.06)
    assert credit['capacity']>old['capacity']


def test_prefilled_duplicate_unchanged_value_is_still_rejected(run):
    with pytest.raises(ValueError,match='两次'):
        parse_template(prefilled(run)+'\n'+prefilled(run).splitlines()[1],run)


def test_explicit_zero_and_existing_overrides_are_preserved(run):
    amended=deepcopy(run)
    amended['input_profile'].update(credit_limit=0,secured_rate=.03)
    values=current_values(amended)
    assert values['credit_limit']==0 and values['secured_rate']==.03
    result=parse_template(prefilled(amended,{'factoring_limit':0,'requested_amount':5e8}),amended)
    assert result['changes']=={'requested_amount':5e8,'factoring_limit':0}
