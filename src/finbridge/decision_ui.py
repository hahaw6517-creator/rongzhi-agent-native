"""Render the financing decision before its diagnostic evidence."""
import pandas as pd
import streamlit as st

from finbridge.workflow import fmt


def render_financing_plan(run, *, compact=False):
    plan = run["outputs"].get("design_financing_plan")
    if not plan:
        st.info("此任务为旧版快照，尚无完整融资决策方案。请回到任务工作台重新启动任务。")
        return
    funding, primary, repayment = plan["funding"], plan["primary"], plan["repayment"]
    st.subheader("融资决策方案", icon=":material/strategy:")
    with st.container(border=True):
        st.caption("决策结论 / " + plan["industry"]["name"])
        st.subheader(plan["decision"]["title"])
        st.markdown(plan["decision"]["summary"])
        for reason in plan["decision"]["reasons"]:
            st.markdown("- " + reason)
        a, b, c = st.columns(3)
        a.metric("本次使用自有资金", fmt(funding["internal_used"], "元"))
        b.metric("主方案拟议债务", fmt(funding["proposed_debt"], "元"))
        c.metric("尚未落实缺口", fmt(funding["unallocated_gap"], "元"))
        st.caption("主方案与备选方案互为替代，不能重复加总。尚未落实缺口不计作已筹资金；拟议债务仍需机构核验。")
    with st.container(border=True):
        st.subheader("主方案 · " + primary["title"])
        st.badge(primary["status"], color="orange")
        st.caption("方案拟议金额：" + fmt(primary["amount"], "元"))
        st.markdown(primary["reason"])
        st.markdown("**还款匹配：**" + primary["repayment_match"])
        st.markdown("**启动条件：**" + "；".join(primary["conditions"]))
        st.caption("专项材料：" + "、".join(primary["materials"]))
    if compact:
        st.caption("完整的备选方案、期限与成本、行业适配、实施阶段和退出条件见“方案与测算”，下载报告也包含这些内容。")
        return
    st.subheader("备选方案与切换条件")
    for alternate in plan["alternatives"]:
        with st.container(border=True):
            st.markdown("**" + alternate["title"] + "** · " + alternate["status"])
            st.caption("替代方案金额：" + fmt(alternate.get("amount"), "元"))
            st.markdown(alternate["reason"])
            st.caption("未作为首选：" + alternate.get("why_not_primary", "需进一步核验"))
            st.markdown("**切换前确认：**" + "；".join(alternate["conditions"]))
    st.subheader("金额、期限与成本的取舍")
    st.caption("预算假设：CFADS下降20%、利率上行1个百分点、压力DSCR目标1.20。为本项目演示安全余量，非监管统一门槛。")
    a, b, c = st.columns(3)
    a.metric("测算期限", str(repayment["months"]) + "个月")
    b.metric("假设月供", fmt(repayment["monthly_payment"], "元"))
    c.metric("假设总利息", fmt(repayment["total_interest"], "元"))
    st.caption("等额本息仅为统一预算口径，未计担保、评估和服务费；实际保理或租赁报价、付款结构须另行核验。")
    if plan.get("term_comparison"):
        st.dataframe(pd.DataFrame([{
            "期限（月）": term["months"], "现金流债务预算上限": fmt(term.get("debt_capacity"), "元"),
            "拟议债务": fmt(term.get("proposed_debt"), "元"), "尚未落实缺口": fmt(term.get("remaining_gap"), "元"),
            "压力DSCR": fmt(term.get("stress_dscr"), "倍"), "适用条件": term["status"],
        } for term in plan["term_comparison"]]), hide_index=True, alt="不同期限对应的债务预算和剩余资金缺口")
    with st.expander("查看资金结构与债务预算公式"):
        st.markdown(f"资金需求 {fmt(funding['need'], '元')} − 本次使用自有资金 {fmt(funding['internal_used'], '元')} = 外部缺口 {fmt(funding['gap'], '元')}")
        st.markdown("现金流测算债务预算上限：" + fmt(funding["debt_capacity"], "元"))
        st.code(repayment["capacity_formula"], language=None)
        for key, label in (("base", "基准"), ("stress", "双重压力")):
            scenario = repayment.get(key) or {}
            st.markdown(f"{label}：CFADS {fmt(scenario.get('cfads'), '元')}；合计年化偿债 {fmt(scenario.get('total_annual_service'), '元')}；整体DSCR {fmt(scenario.get('dscr'), '倍')}")
    industry = plan["industry"]
    with st.expander("行业痛点与专项核验 · " + industry["name"], expanded=True):
        for pain in industry["pain_points"]:
            st.markdown("- " + pain)
        for tool in industry["financing_tools"]:
            st.markdown("- " + tool)
        st.markdown("**还款周期匹配：**" + industry["repayment_match"])
        st.caption("专项材料：" + "、".join(industry["verification_materials"]))
    st.subheader("决策门槛")
    st.dataframe(pd.DataFrame([{"检查项": gate["label"], "状态": gate["status"], "判断依据": gate["detail"], "证据": str(gate["evidence"])} for gate in plan["gates"]]), hide_index=True, alt="数据、偿付能力、风险与融资条件的决策检查结果")
    st.subheader("实施安排")
    for phase in plan["schedule"]:
        with st.container(border=True):
            st.markdown("**" + phase["phase"] + "** · " + phase["owner"])
            for action in phase["actions"]:
                st.markdown("- " + action)
            st.caption("进入下一阶段条件：" + phase["exit_condition"])
    with st.expander("受阻与退出预案", expanded=True):
        for trigger in plan["exit_triggers"]:
            st.markdown("**" + trigger["trigger"] + "**：" + trigger["action"])
        for limit in plan["limitations"]:
            st.caption(limit)
