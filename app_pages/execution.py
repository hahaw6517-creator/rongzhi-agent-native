import streamlit as st
from finbridge.ui import page_header, result_guard, evidence_table
from finbridge.workflow import TOOLS, fmt
from finbridge.industry_context_ui import render_industry_context
from finbridge.terminology import render_terms, REPAYMENT_HELP

page_header("FINBRIDGE / FINANCIAL ANALYSIS", "财务分析", "查看盈利、偿债、现金流和周转指标，定位资金占用与风险来源。")
run = result_guard()
if run.get("public_analysis") is not None:
    from finbridge.public_ui import execution_page
    execution_page(run)
    st.stop()
out = run["outputs"]
cols = st.columns(3)
cols[0].metric("已完成工具", len(out), border=True)
cols[1].metric("可计算财务指标", sum(v["value"] is not None for v in out["calculate_ratios"].values()), border=True)
cols[2].metric("引用知识条目", len(out["retrieve_knowledge"]["documents"]), border=True)
evidence, risk, context, timeline, snapshot = st.tabs(["财务指标", "风险评估", "行业与地区", "计算过程", "原始数据"])
with context:
    render_industry_context(run)
with timeline:
    st.caption("记录工具执行过程，不展示模型的内部思维链。行业地区工具耗时包含检索与专项模型请求；其他工具时间不含规划模型请求。")
    for event in run["events"]:
        state_icon = ":material/check_circle:" if event["status"] == "完成" else ":material/error:"
        with st.expander(f"{event['step']:02d} · {event['label']} · {event['status']} · {event['duration_ms']:.1f} ms", icon=state_icon):
            st.caption("工具：" + event["tool"])
            st.json({"arguments": event["arguments"], "observation": event["result"]}, expanded=False)
    st.download_button("下载执行证据 JSON", __import__('json').dumps(run, ensure_ascii=False, indent=2), run["id"] + "-evidence.json", "application/json", icon=":material/download:")
with evidence:
    st.caption(REPAYMENT_HELP)
    render_terms(("CFADS", "DSCR", "EBIT", "EBITDA"))
    st.dataframe(evidence_table(out["calculate_ratios"]), hide_index=True, alt="财务指标、公式、来源与缺失原因")
    st.caption("不同单位的财务指标分别列示，不混用单一坐标轴。缺失字段不会被自动补零。")
    for driver in out["prepare_deliverables"].get("drivers", []):
        st.markdown("**" + driver["title"] + "：" + fmt(driver["value"], driver["unit"]) + "**")
        st.caption(driver["reason"])
with risk:
    st.caption(out["assess_risk"]["methodology"])
    for dimension in out["assess_risk"]["dimensions"].values():
        with st.container(border=True):
            a, b = st.columns([3, 1])
            a.subheader(dimension["label"])
            a.caption(dimension["data_sufficiency"])
            b.badge(dimension["risk_level"], color="red" if dimension["risk_level"] == "较高" else "orange" if dimension["risk_level"] in {"关注", "无法判断"} else "green")
            if dimension["evidence"]:
                st.dataframe([{"指标": e["metric"], "实际结果": fmt(e["value"], e["unit"]), "本项目筛查规则": e.get("rule_label", e["rule"]), "是否触发": "是" if e["triggered"] else "否", "报告期": e["period"]} for e in dimension["evidence"]], hide_index=True, alt="风险阈值与实际触发情况")
            else:
                st.caption("没有足够数据，无法判断。")
with snapshot:
    st.json({"data_source": run["source"], "data_fingerprint": run["fingerprint"], "financial_data": run["data"], "task_profile": run["profile"]}, expanded=True)
