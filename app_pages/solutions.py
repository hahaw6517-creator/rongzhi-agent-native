import pandas as pd
import streamlit as st
from finbridge.ui import page_header, result_guard
from finbridge.workflow import fmt, simulate_repayment, KNOWLEDGE
from finbridge.portfolio_ui import render_portfolio
from finbridge.industry_context_ui import render_industry_context
from finbridge.terminology import REPAYMENT_HELP

page_header("FINBRIDGE / FINANCING PORTFOLIO", "融资组合", "在渠道容量、资金用途和压力偿债约束下，计算金额分配、成本与风险。")
run = result_guard()
if run.get("public_analysis") is not None:
    from finbridge.public_ui import solutions_page
    solutions_page(run)
    st.stop()
out = run["outputs"]
render_portfolio(run)
render_industry_context(run, compact=True)
with st.expander("融资方式与使用边界（参考）"):
    st.subheader("融资路径的核验依据")
    st.caption("以下为融资方式的准备建议，不包含银行产品、获批额度、实际利率或审批承诺。")
    for i in range(0, len(out["match_routes"]), 2):
        for j, (column, route) in enumerate(zip(st.columns(2), out["match_routes"][i:i+2])):
            with column, st.container(border=True):
                st.caption(f"PATH {i+j+1:02d} / {route['source']}")
                st.subheader(route["name"])
                st.caption(route["subtitle"])
                st.badge(route["status"], color="green" if route["status"] == "适合进一步核验" else "orange" if route["status"] not in {"用途不符", "暂不适配"} else "gray")
                for reason in route["evidence"]:
                    st.markdown("- " + reason)
                with st.container():
                    for condition in route["conditions"]:
                        st.markdown("- " + condition)
                    st.caption("材料：" + "、".join(route["materials"]))
                    source = next(k for k in KNOWLEDGE if k["id"] == route["source"])
                    st.link_button("查看依据 · " + source["title"], source["url"], icon=":material/open_in_new:")

with st.expander("比较：原始全额请求的压力测算"):
    st.subheader("原始请求压力实验室", icon=":material/query_stats:")
    st.caption(REPAYMENT_HELP)
    with st.container(border=True):
        st.caption("按原始外部缺口 " + fmt(out["simulate_repayment"]["gap"], "元") + " 测算，与上方调整后的主方案债务预算不同。本区不会修改上方融资组合；修改假设仅影响原始全额请求实验；报告保留生成时的假设。")
        a, b, c = st.columns(3)
        rate = a.slider("假设年利率（%，非市场报价）", 0.0, 100.0, float(run["profile"]["assumed_rate"] * 100), 0.1)
        drop = b.slider("还款现金（CFADS）压力降幅（%）", 0, 80, 20, 5)
        rate_up = c.slider("利率上行（百分点）", 0.0, 5.0, 1.0, 0.1)
        if out["inspect_data"]["blocked"]:
            st.error("输入数据存在阻断问题，请先修正后重新执行。")
        else:
            simulation = simulate_repayment(run["data"], dict(run["profile"], assumed_rate=rate/100), cash_drop=drop/100, rate_up=rate_up/100)
            frame = pd.DataFrame([{"情景": s["scenario"], "假设年利率": f"{s['assumed_rate']:.1%}", "CFADS降幅": f"{s['cash_drop']:.0%}",
                "新增未来12个月本息（万元）": round(s["new_annual_service"]/10000, 2), "含现有债务DSCR": s["dscr"]} for s in simulation["scenarios"]])
            st.dataframe(frame, hide_index=True, alt="四种现金流及利率情景的未来12个月偿债与覆盖率")
            if simulation["available"]:
                chart = pd.DataFrame({"情景": [s["scenario"] for s in simulation["scenarios"]], "含现有债务DSCR": [s["dscr"] for s in simulation["scenarios"]]}).set_index("情景")
                st.bar_chart(chart, color="#087F73", height=250, alt="四种情景的债务偿付覆盖率比较")
                if any(s["dscr"] is not None and s["dscr"] < 1 for s in simulation["scenarios"]):
                    st.warning("存在覆盖率低于1的情景：假设现金流不足以覆盖未来12个月本息，应调整金额、期限或还款安排后复核。")
            else:
                st.warning(simulation["missing_reason"])
            st.caption(simulation["note"])
if st.button("前往交付与行动", type="primary", icon=":material/arrow_forward:"):
    st.switch_page("app_pages/delivery.py")
