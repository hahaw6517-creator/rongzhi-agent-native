"""Re-solve hypothetical adjustments, preserving the original task and market basis."""
from copy import deepcopy
import math
from numbers import Real
from finbridge.market_rules import effective_portfolio
from finbridge.portfolio import build_financing_portfolio
from finbridge.task_focus import build_task_focus

ADJUSTMENTS = {
    "融资组合": (("internal_funds", "试算自有资金", "万元", 0., 1e15),
                 ("confirmed_credit_limit", "试算已确认可用信用额度", "万元", 0., 1e15)),
    "风险分析": (("cash_flow_available_for_debt_service", "试算年度还款现金", "万元", -1e15, 1e15),
                 ("scheduled_debt_service", "试算已有债务年度本息", "万元", 0., 1e15)),
    "方案比较": (("cash_drop", "试算还款现金下降", "%", .2, .4),
                 ("rate_up", "试算利率上行", "个百分点", .01, .05)),
}


def adjustment_defaults(run):
    stress=(effective_portfolio(run["outputs"]) or {}).get("algorithm", {}).get("planning_stress", {})
    result={}
    for key, *_ in ADJUSTMENTS[run["goal"]]:
        if key in {"cash_drop", "rate_up"}:
            result[key]=stress.get(key, .2 if key=="cash_drop" else .01)
        else:
            value=run["profile"].get(key)
            result[key]=run["data"].get(key) if value in (None, "") else value
    return result


def preview_adjustment(run, changes):
    from finbridge.workflow import DiligenceRun
    spec={row[0]:row for row in ADJUSTMENTS[run["goal"]]}
    if not isinstance(changes, dict) or not changes or set(changes)-set(spec):
        raise ValueError("只能试算当前分析重点允许调整的字段")
    for key,value in changes.items():
        if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value) or not spec[key][3] <= value <= spec[key][4]:
            raise ValueError("试算参数超出范围："+spec[key][1])
    base=effective_portfolio(run["outputs"])
    if not base or not base.get("available"):
        raise ValueError("请先修正基础数据，才能进行调整试算")
    data,profile=deepcopy(run["data"]),deepcopy(run["profile"])
    stress=deepcopy(base["algorithm"]["planning_stress"])
    for key,value in changes.items():
        if key in stress:
            stress[key]=value
        elif key=="internal_funds":
            profile[key]=value
        else:
            data[key]=value
            if key in profile:
                profile[key]=value
    engine=DiligenceRun(data,profile,run["goal"],"假设调整试算")
    for tool in ("inspect_data","calculate_ratios","assess_risk"):
        engine.execute(tool)
    outputs=engine.result["outputs"]
    plan=build_financing_portfolio(engine.data,profile,quality=outputs["inspect_data"],risk=outputs["assess_risk"],planning_stress=stress)
    outputs["optimize_financing_portfolio"]=plan
    focus=build_task_focus(engine.data,profile,outputs,run["goal"],plan)
    return dict(goal=run["goal"], changes=changes, plan=plan, focus=focus,
        delta={key:plan["funding"][key]-base["funding"][key] if plan["funding"].get(key) is not None else None
            for key in ("debt_total","unfunded_gap","fees_due")},
        note="仅按假设重新求解，不调用模型或重新联网；沿用本任务市场压力口径。未保存到企业档案，也未改动原报告；真实采用前须核验现金、额度及还款安排，再更新数据重新生成正式任务。")


def render_adjustment(run):
    import streamlit as st
    import pandas as pd
    from finbridge.result_review import money
    base=effective_portfolio(run["outputs"])
    if not base or not base.get("available"):
        return
    st.subheader("改一个条件，看看结果怎么变")
    st.caption("假设试算 · 重新计算指标和风险、重新求解组合；不会覆盖当前结果或替你取得额度。")
    defaults=adjustment_defaults(run)
    with st.form("adjustment_"+run["id"]):
        changes={}
        for key,label,unit,low,high in ADJUSTMENTS[run["goal"]]:
            factor=10000 if unit=="万元" else .01
            value=defaults[key]
            entered=st.number_input(label+"（"+unit+"）",min_value=low/factor,max_value=high/factor,
                value=float(value/factor) if value is not None else None,step=1.0 if unit=="万元" else .1)
            changes[key]=entered*factor if entered is not None else None
        clicked=st.form_submit_button("计算调整后的结果")
    slot="adjustment_result_"+run["id"]
    if clicked:
        try:
            if any(v is None for v in changes.values()):
                raise ValueError("请先核实并补齐试算字段")
            st.session_state[slot]=preview_adjustment(run,changes)
        except ValueError as exc:
            st.session_state.pop(slot,None)
            st.warning(str(exc))
    result=st.session_state.get(slot)
    if result:
        st.write("**调整试算结果 · 不是原报告**")
        st.write(result["focus"]["summary"])
        if not result["plan"]["available"]:
            st.warning("调整后的条件未通过核验，不能据此给出借款金额。")
            for flag in result["plan"].get("risk_flags", []):
                st.caption(flag)
        st.dataframe(pd.DataFrame([{"对比项目":label,"原方案":money(base["funding"].get(key)),"试算方案":money(result["plan"]["funding"].get(key)),"变化（试算减原方案）":money(result["delta"].get(key))} for label,key in (("新增借款","debt_total"),("用途缺口","unfunded_gap"),("一次性费用","fees_due"))]),hide_index=True,alt="假设调整后重新求解的借款、缺口及费用变化")
        risk=result["focus"].get("risk",{})
        if risk.get("threshold"):
            t=risk["threshold"]
            st.write("调整后每年至少需还款现金 "+money(t["minimum_cash"])+"；通过设定压力还需改善 "+money(t["cash_improvement"])+"。")
        for p in result["focus"].get("comparison",{}).get("options",[]):
            st.write(p["title"]+"：借款"+money(p["debt"])+"，用途缺口"+money(p["gap"])+"，全期限利息与费用"+money(p["total_cost"])+"。")
        st.caption(result["note"])
