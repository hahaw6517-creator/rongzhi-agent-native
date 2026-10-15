from finbridge.real_case import real_cases
from finbridge.working_capital_year import optimize_year


def test_failed_annual_case_names_actual_cash_constraints_and_quantifies_them():
    case=real_cases()[2]
    plan=optimize_year(case['data'],case['profile'])
    summary=plan['decision_summary']
    assert not summary['verified']
    assert len(summary['blockers'])==2
    first,second=summary['blockers']
    assert '已有债务一年本息' in first['evidence']
    assert '即使不新增借款也差' in first['evidence']
    assert '营业成本' in second['evidence'] and '均匀分配' in second['evidence']
    assert '敏感性假设' in second['action']
    assert '产品用途、资产池或' not in summary['text']
    assert summary['actions']==[b['action'] for b in summary['blockers']]


def test_successful_annual_case_does_not_display_failed_constraint_explanations():
    case=real_cases()[1]
    plan=optimize_year(case['data'],case['profile'])
    assert plan['verification']['passed']
    assert plan['decision_summary']['blockers']==[]
