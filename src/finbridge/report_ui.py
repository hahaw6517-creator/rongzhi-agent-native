"""Reviewer-facing results, without the workspace's input repair controls."""
import pandas as pd
import streamlit as st
from finbridge.report_brief import build_report_brief
from finbridge.result_review import money
from finbridge.workflow import fmt
from finbridge.terminology import REPAYMENT_HELP, CASH_GAP_HELP, render_terms


def render_report(run):
    b = build_report_brief(run)
    st.caption("成果摘要 · 分析重点："+b["goal"]+" · 生成时快照")
    st.subheader("这次分析在解决什么问题")
    st.write(b["question"])
    st.caption(f"{b['company']} · {b['industry']} · {b['region']} · {b['period']} · {b['source']}")
    r = b["request"]
    st.write("资金需求 "+money(r["need"])+"，计划自有资金 "+money(r["own"])+f"，{r['months']}个月，用于{r['purpose']}。")
    st.subheader(b["title"])
    if b["available"]:
        st.info(b["conclusion"])
    else:
        st.warning(b["conclusion"])
    f = b["funding"]
    if b["goal"] == "融资组合":
        cols=st.columns(3)
        for col,label,key in zip(cols,["可配置新增借款","用途还差的钱","另需一次性费用"],["debt_total","unfunded_gap","fees_due"]):
            col.metric(label,money(f.get(key)),border=True)
        if b["channels"]:
            st.dataframe(pd.DataFrame([{"渠道":s["channel"],"安排金额":money(s["amount"]),"期限":f"{s['months']}个月","假设利息及费用":money(s["cost"])} for s in b["channels"]]),hide_index=True,alt="本次融资安排摘要")
    elif b["goal"] == "风险分析":
        t=b["threshold"]
        if t:
            a,c,d=st.columns(3)
            a.metric("每年至少需还款现金",money(t["minimum_cash"]),border=True)
            c.metric("还款现金下降临界点","已低于安全线" if t["already_below"] else f"{t['cash_drop_limit']:.1%}" if t["cash_drop_limit"] is not None else "不适用",border=True)
            d.metric("通过设定压力还需改善",money(t["cash_improvement"]),border=True)
            st.caption(t["note"])
    elif b["comparison"]:
        st.dataframe(pd.DataFrame([{"方案":p["title"],"筹到的借款":money(p["debt"]),"用途缺口":money(p["gap"]),"全期限成本":money(p["total_cost"]),"加息后一年内新增本息":money(p["new_service"]),"同一压力下覆盖倍数":fmt(p["common_stress_dscr"],"倍")} for p in b["comparison"]["options"]]),hide_index=True,alt="不同方案的筹资效果与付出代价")
        for text in b["comparison"]["duplicates"]:
            st.caption(text)
        st.caption(b["comparison"]["note"])
    st.subheader("哪些数据支撑这个结论")
    st.dataframe(pd.DataFrame([{"关键指标":m["label"],"本次结果":m["value"],"为什么看它":m["why"],"待核对":m["issue"] or "—"} for m in b["metrics"]]),hide_index=True,alt="按分析重点挑选的关键财务指标及用途")
    st.caption(REPAYMENT_HELP)
    st.subheader("最需要注意的风险")
    for r in b["risks"]:
        st.write("**"+r["question"]+" · "+r["level"]+"**")
        st.caption(r["reason"])
    st.subheader("压力下还能不能还款")
    if b["scenarios"]:
        st.dataframe(pd.DataFrame([{"情景":s["label"],"年度还款现金":money(s["cfads"]),"一年内已有及新增本息":money(s["new_annual_service"]+s["existing_annual_service"]),"覆盖倍数":fmt(s["dscr"],"倍"),"距1.20倍安全线还需年度现金":money(s["gap_to_target"])} for s in b["scenarios"]]),hide_index=True,alt="主方案在基准、双重压力和额外恶化情景下的还款结果")
        st.caption(CASH_GAP_HELP)
    else:
        st.warning("数据未齐备或未通过核验，暂不能验证偿付能力。")
    st.subheader("建议怎么做，以及要付出什么")
    for i,s in enumerate(b["strategies"],1):
        with st.container(border=True):
            st.write(f"**{i}. {s['title']}**")
            st.write(s["detail"])
    st.subheader("近期市场有没有改变结论")
    if b["market"]["changed"]:
        st.info("本次结论采用近期证据触发的市场压力组合；金额已按调整后的情景重新计算。基础方案只作对照，不能叠加。")
    st.write(b["market"]["impact"])
    st.caption(b["market"]["source_status"])
    for item in b["market"]["evidence"]:
        st.write(item["title"]+"："+item["analysis"])
        st.caption("依据："+("、".join(item["source_ids"]) or "模型判断，未引用来源"))
    with st.expander("资料引用与完整行业地区依据"):
        from finbridge.industry_context_ui import render_industry_context
        render_industry_context(run,compact=True)
    with st.expander("本次方法、指标公式和结论边界"):
        st.write(b["methods"])
        for m in b["metrics"]:
            st.caption(m["label"]+"："+m["formula"])
        st.write(b["boundary"])
    render_terms()
    st.caption("如需改数据、调整条件或查看完整五情景实验，请到融资组合页；本页集中展示本次分析成果。")
    return b
