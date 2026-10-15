"""Two-observation cash conversion forecast and a held-out annual check."""
import math
from finbridge.financial_history import annual_records


def predict_from_two(older, newer, growth=None):
    if newer['year'] != older['year'] + 1:return None
    values=[r['values'] for r in (older,newer)]
    if any(not isinstance(v.get(k),(int,float)) or not math.isfinite(v[k]) for v in values for k in ('revenue','operating_cash_flow')):return None
    if any(v['revenue']<=0 for v in values):return None
    observed_growth=values[1]['revenue']/values[0]['revenue']-1
    rate=max(-.3,min(.5,observed_growth)) if growth is None else growth
    conversion=sum(v['operating_cash_flow']/v['revenue'] for v in values)/2
    revenue=values[1]['revenue']*(1+rate)
    return dict(target_year=newer['year']+1,source_years=[older['year'],newer['year']],
        source_revenue=[v['revenue'] for v in values],source_cash=[v['operating_cash_flow'] for v in values],
        cash_conversion=conversion,growth=rate,observed_growth=observed_growth,
        projected_revenue=revenue,annual_operating=revenue*conversion,
        formula='预测经营净现金＝预计收入×前两年经营净现金/收入比例的平均值',
        basis='预计收入＝第二年收入×(1＋增长情景)；默认延续两年收入增幅并限制在-30%至50%，用户可调整未来增长情景。保留经营现金正负号。',
        limitation='两年数据只支持简化情景测算，不是训练模型；并购、一次性收付款和季节性可能造成较大误差。')


def cash_forecast(raw,growth=None,calibrate=False,calibration_share=.5,calibration_limit=.3):
    rows=annual_records(raw)
    future=predict_from_two(*rows[-2:],growth) if len(rows)>=2 else None
    validation=None
    if len(rows)>=3:
        prior=predict_from_two(*rows[-3:-1])
        actual=rows[-1]['values'].get('operating_cash_flow')
        if prior and prior['target_year']==rows[-1]['year'] and isinstance(actual,(int,float)):
            error=prior['annual_operating']-actual
            validation={**prior,'actual':actual,'error':error,'absolute_percentage_error':abs(error)/abs(actual) if abs(actual)>1 else None,
                'note':'先仅用前两年数据计算第三年，再对照第三年实际值。实际值不参与这次历史预测，不据一次检验宣称预测准确。'}
    if calibrate and future:
        original=future['annual_operating'];adjustment=0.;method='未取得有效历史检验，保留原始值';limit=max(abs(original),abs(rows[-1]['values'].get('operating_cash_flow',0)))*calibration_limit
        if validation:
            # One residual is not a fitted error distribution. Shrink its transfer,
            # cap it, and never mechanically promote negative cash to positive.
            adjustment=max(-limit,min(limit,-calibration_share*validation['error']))
            if original<=0:adjustment=min(0,adjustment)
            method=f'转移上一轮有符号误差的{calibration_share:.0%}，修正额不超过本期预测或最新实际现金较大绝对值的{calibration_limit:.0%}；负现金不因校正转正。系显式稳健假设，非经样本训练参数。'
        future.update(uncalibrated_operating=original,calibration_adjustment=adjustment,annual_operating=original+adjustment,calibration_method=method,calibration_error=validation['error'] if validation else None,calibration_share=calibration_share,calibration_limit=calibration_limit)
    return dict(future=future,validation=validation)
