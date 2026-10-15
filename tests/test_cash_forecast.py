from copy import deepcopy
import pytest
from finbridge.cash_forecast import cash_forecast,predict_from_two
from finbridge.real_case import real_case
from finbridge.public_finance import public_model


def row(year,revenue,cash):return dict(year=year,values=dict(revenue=revenue,operating_cash_flow=cash))


def test_two_year_prediction_and_zero_or_negative_cash():
    p=predict_from_two(row(2023,100,10),row(2024,110,22))
    assert p['projected_revenue']==pytest.approx(121)
    assert p['annual_operating']==pytest.approx(18.15)
    assert predict_from_two(row(2023,0,10),row(2024,110,22)) is None
    assert predict_from_two(row(2022,100,10),row(2024,110,22)) is None
    assert predict_from_two(row(2023,100,-10),row(2024,100,-20))['annual_operating']==pytest.approx(-15)


def test_holdout_prediction_does_not_use_third_year_actuals():
    d=real_case()['data'];before=cash_forecast(d)
    changed=deepcopy(d);changed['revenue']*=2;changed['operating_cash_flow']*=3
    after=cash_forecast(changed)
    assert before['validation']['annual_operating']==after['validation']['annual_operating']
    assert before['validation']['actual']!=after['validation']['actual']
    assert before['future']['annual_operating']!=after['future']['annual_operating']
    assert before['validation']['source_years']==[2023,2024]
    assert before['future']['source_years']==[2024,2025]
    assert before['future']['target_year']==2026


def test_financing_cash_uses_same_future_forecast_and_conservative_floor():
    c=real_case();m=public_model(c['data'],c['profile'])
    assert m['forecast_ocf']==m['cash_prediction']['future']['annual_operating']
    assert m['conservative_cash']<=m['cash']
    assert m['conservative_cash']<=m['diagnostics']['support']['conservative_ocf']-m['capex']*m['assumptions']['maintenance_share']
    adjusted=public_model(c['data'],{**c['profile'],'forecast_growth':0})
    assert adjusted['cash_prediction']['future']['growth']==0
    assert adjusted['cash_prediction']['validation']==m['cash_prediction']['validation']
