"""Plain-language, goal-specific summaries before the shared audit evidence."""
import pandas as pd
import streamlit as st
from finbridge.task_focus import build_task_focus
from finbridge.result_review import money
from finbridge.terminology import REPAYMENT_HELP


def render_task_focus(run):
    focus = run["outputs"].get("prepare_deliverables", {}).get("task_focus")
    if not focus:
        focus = build_task_focus(run["data"], run["profile"], run["outputs"], run["goal"])
    st.caption("本次分析重点 · " + focus["goal"] + " · 以下内容根据本次数据计算")
    st.subheader(focus["title"])
    st.write(focus["summary"])
    st.caption(REPAYMENT_HELP)
    if focus.get("funding_steps"):
        for step in focus["funding_steps"]:
            with st.container(border=True):
                st.write(step["channel"] + "：" + money(step["amount"]))
                st.caption(step["reason"])
                st.write("这笔借款按假设计算，全期限利息和费用共 " + money(step["cost"]) + "。")
    risk = focus.get("risk")
    if risk:
        t=risk["threshold"]
        if t:
            a,b,c=st.columns(3)
            limit = "已低于安全线" if t["already_below"] else f"{t['cash_drop_limit']:.1%}" if t["cash_drop_limit"] is not None else "不适用"
            a.metric("还款现金最多可下降", limit, border=True)
            b.metric("每年至少要有的还款现金", money(t["minimum_cash"]), border=True)
            c.metric("通过设定压力还需改善现金", money(t["cash_improvement"]), border=True)
            st.caption("还款现金指可用于还本付息的现金（CFADS）。临界点固定本组合与加息假设，达到项目覆盖率1.20；不是营业收入的降幅，也不是违约预测。")
            if t["cash_improvement"] > .01:
                st.warning("至少增加可靠的年度还款现金 " + money(t["cash_improvement"]) + "，或协商减少对应年度还本付息 " + money(t["service_reduction"]) + "。两条是替代路径，不能重复计入。")
        st.markdown("**先处理哪些问题**")
        st.dataframe(pd.DataFrame([{"问题": r["question"], "需要关注的程度": r["level"], "依据": r["reason"]} for r in risk["ranked"]]),
            hide_index=True, alt="按项目规则严重程度排列的财务风险与实际触发依据")
        improvements=[d for d in risk["improvements"] if d["unit"] == "元"][:2]
        if improvements:
            st.markdown("**改善试算：哪些地方可能减少资金占用**")
            for d in improvements:
                st.write(d["title"] + "：" + money(d["value"]))
                st.caption(d["action"] + " 这是条件式试算，不能当作已回款或已筹到的资金。")
        st.caption(risk["scope"])
    compare=focus.get("comparison")
    if compare:
        if compare["options"]:
            st.dataframe(pd.DataFrame([{"方案": p["title"], "新增借款": money(p["debt"]), "还差的钱": money(p["gap"]),
                "全期限利息与费用": money(p["total_cost"]), "加息后新增一年内还款": money(p["new_service"]),
                "统一压力下覆盖倍数": f"{p['common_stress_dscr']:.2f}" if p["common_stress_dscr"] is not None else "无本息负担"} for p in compare["options"]]),
                hide_index=True, alt="实际重新求解的不同融资方案在借款额、缺口、成本和同口径还款压力上的比较")
            for p in compare["options"]:
                with st.expander(p["title"] + " · 适合什么情况、具体借法"):
                    st.write(p["reason"])
                    st.caption(p["status"])
                    for channel in p["composition"]:
                        st.write(channel["name"]+"："+money(channel["amount"])+f"，{channel['months']}个月，假设年利率{channel['rate']:.1%}")
                    if not p["composition"]:
                        st.write("本方案没有新增借款，需先处理已有债务或渠道条件。")
        for duplicate in compare["duplicates"]:
            st.caption(duplicate)
        st.caption(compare["note"])
    return focus
