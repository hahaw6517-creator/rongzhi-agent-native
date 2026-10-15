import pytest
from finbridge.working_capital_year import tail_cash_pressure,cvar_explanation


@pytest.mark.parametrize('alpha',[.5,.8,.9,.95])
def test_tail_breakdown_reconstructs_same_cvar_and_cash_changes(alpha):
    tests=[dict(id='base' if i==0 else str(i),label=str(i),annual_cash=100-v,total_service=10+i,gap_to_target=0) for i,v in enumerate([0,5,10,15,20,30])]
    losses,cvar=tail_cash_pressure(tests,100,alpha)
    for row,loss in zip(tests,losses):row['tail_cash_pressure']=loss
    detail=cvar_explanation(tests,alpha)
    assert sum(r['included_weight'] for r in detail['rows'])==pytest.approx(1-alpha)
    assert sum(r['tail_share'] for r in detail['rows'])==pytest.approx(1)
    assert sum(r['contribution'] for r in detail['rows'])==pytest.approx(cvar)
    for row in detail['rows']:
        assert max(0,row['cash_decline']+row['service_increase'])==pytest.approx(row['loss'])
    if alpha==.8:
        assert [r['tail_share'] for r in detail['rows']]==pytest.approx([5/6,1/6])


def test_zero_losses_do_not_imply_zero_safety_gap():
    rows=[dict(id='base' if i==0 else str(i),label=str(i),annual_cash=0,total_service=10,tail_cash_pressure=0,gap_to_target=12) for i in range(6)]
    detail=cvar_explanation(rows,.8)
    assert sum(r['contribution'] for r in detail['rows'])==0
    assert detail['max_safety_gap']==12
