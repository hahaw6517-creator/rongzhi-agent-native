"""Business-facing financing mix and financial drivers."""
import altair as alt
import pandas as pd
import streamlit as st

from finbridge.workflow import fmt
from finbridge.market_rules import effective_portfolio
from finbridge.terminology import REPAYMENT_HELP, STRESS_HELP, CASH_GAP_HELP, render_terms


def _render_portfolio_details(run, *, compact=False):
    plan = effective_portfolio(run["outputs"])
    if not plan:
        st.info("当前是旧版结果。请返回分析工作台，重新生成融资组合。")
        return
    f = plan["funding"]
    st.subheader("融资组合建议", icon=":material/pie_chart:")
    if run["outputs"].get("analyze_industry_region", {}).get("market_decision", {}).get("changed"):
        st.info("当前主建议采用近期证据触发的市场压力组合。原始基础组合及变化原因见下方行业地区分析；两套组合不可叠加。")
    st.badge(plan["status"], color="orange")
    cols = st.columns(4)
    for col, label, key in zip(cols, ["资金需求", "投入自有资金", "组合债务本金", "尚未覆盖用途缺口"], ["need", "internal_used", "debt_total", "unfunded_gap"]):
        col.metric(label, fmt(f.get(key), "元"), border=True)
    st.caption(f.get("note", ""))
    for flag in plan["risk_flags"]:
        st.warning(flag)
    if not plan["available"]:
        st.info("财务指标仍按已上传数据计算。补齐年度现金流、存量本息及渠道条件后，可重新生成金额组合。")
        return
    parts = [{"资金来源": "自有资金", "金额（万元）": f["internal_used"]/10000}]
    parts += [{"资金来源": c["name"], "金额（万元）": c["amount"]/10000} for c in plan["composition"] if c["amount"] > 0]
    if f["unfunded_gap"] > 0:
        parts.append({"资金来源": "待落实缺口", "金额（万元）": f["unfunded_gap"]/10000})
    left, right = st.columns([1, 2])
    with left:
        chart = alt.Chart(pd.DataFrame(parts)).mark_arc(innerRadius=65).encode(
            theta=alt.Theta("金额（万元）:Q"), color=alt.Color("资金来源:N", scale=alt.Scale(range=["#087F73", "#5B86A6", "#A083AC", "#D3A654", "#72B8A0", "#C95A4F"])),
            tooltip=["资金来源:N", alt.Tooltip("金额（万元）:Q", format=",.2f")],
        ).properties(height=260)
        st.altair_chart(chart, alt="自有资金、各融资渠道及未覆盖缺口占本次资金需求的比例")
    with right:
        st.dataframe(pd.DataFrame([{
            "融资渠道": c["name"], "建议本金": fmt(c["amount"], "元"), "占新增融资": fmt(c["share"], "%"),
            "渠道容量": fmt(c["capacity"], "元"), "假设年利率": fmt(c["rate"], "%"), "期限（月）": c["months"],
            "假设总利息": fmt(c["total_interest"], "元"), "一次性费": fmt(c["total_fee"], "元"),
        } for c in plan["composition"]]), hide_index=True, alt="融资组合各渠道的建议本金、容量、利率、期限及成本")
    st.caption("利率、融资比例、费用和统一等额本息还款方式属于测算输入。只有取得实际合同和报价后，才能比较真实到账额与付款负担。")
    if f.get("fees_due", 0) > 0:
        st.warning("用途本金之外，还需另付一次性费用 " + fmt(f["fees_due"], "元") + "；含费用的总待落实现金为 " + fmt(f["total_unfunded_cash"], "元") + "。")
    st.subheader("为什么这样分配")
    for c in plan["composition"]:
        with st.expander(c["name"] + " · " + fmt(c["amount"], "元"), expanded=c["amount"] > 0):
            st.markdown(c["reason"])
            for assumption in c["assumed"]:
                st.caption(assumption)
    if compact:
        st.caption("完整风险评估、压力测试及算法约束见“融资组合”；下载报告包含全部分析。")
        return
    if plan.get("alternatives"):
        st.subheader("与单一渠道比较")
        st.dataframe(pd.DataFrame([{"方案": a["title"], "债务本金": fmt(a["debt_total"], "元"), "未覆盖用途缺口": fmt(a["unfunded_gap"], "元"), "假设总利息及费用": fmt(a["total_cost"], "元"), "双重压力DSCR": a["stress_dscr"]} for a in plan["alternatives"]]), hide_index=True, alt="同一需求与压力预算下各单渠道替代方案的融资额、缺口、成本与偿债覆盖率")
        st.caption("单渠道方案替代当前组合，金额不能相加；覆盖金额和期限不同，总成本不能直接作为同金额年化成本排名。")
    allocation = plan["purpose_allocation"]
    st.subheader("资金具体用于哪里")
    st.dataframe(pd.DataFrame([{"用途": label, "用途预算": fmt(allocation[budget], "元"), "自有资金": fmt(allocation[internal], "元"), "债务本金": fmt(allocation[debt], "元"), "待落实缺口": fmt(allocation[gap], "元")} for label, budget, internal, debt, gap in (("经营周转", "working_capital_funding_need", "working_internal", "working_debt", "working_unfunded"), ("设备购置", "equipment_funding_need", "equipment_internal", "equipment_debt", "equipment_unfunded"))]), hide_index=True, alt="经营周转和设备购置两类用途的资金预算、资金来源与缺口")
    st.caption(allocation["note"])
    st.subheader("组合压力测试")
    st.caption(REPAYMENT_HELP)
    st.caption("同一融资组合下分别改变还款现金和利率；不会把营业收入下降直接等同于现金流下降。")
    scenarios = pd.DataFrame([{
        "情景": s["label"], "可用于偿债现金流": fmt(s["cfads"], "元"), "新增未来12个月本息": fmt(s["new_annual_service"], "元"),
        "存量未来12个月本息": fmt(s["existing_annual_service"], "元"), "还款覆盖倍数（DSCR）": s["dscr"],
        "达到目标还需年度现金": fmt(s["gap_to_target"], "元"),
    } for s in plan["scenarios"]])
    st.dataframe(scenarios, hide_index=True, alt="五种现金流与利率情景下融资组合的偿债覆盖率和现金不足金额")
    plot = pd.DataFrame([{"情景": s["label"], "DSCR": s["dscr"]} for s in plan["scenarios"] if s["dscr"] is not None])
    if not plot.empty:
        base = alt.Chart(plot).encode(x=alt.X("情景:N", sort=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("DSCR:Q", title="还款覆盖倍数（倍）", scale=alt.Scale(domainMin=0)), tooltip=["情景:N", alt.Tooltip("DSCR:Q", title="还款覆盖倍数", format=".2f")])
        plot["状态"] = plot["DSCR"].map(lambda v: "达到安全线" if v >= 1.2 else "余量偏薄" if v >= 1 else "不足以还款")
        bars = base.mark_bar().encode(color=alt.Color("状态:N", scale=alt.Scale(domain=["达到安全线", "余量偏薄", "不足以还款"], range=["#087F73", "#D3A654", "#C95A4F"]), legend=None))
        values = base.mark_text(dy=-10).encode(text=alt.Text("DSCR:Q", format=".2f"))
        target = alt.Chart(pd.DataFrame({"目标": [1.2]})).mark_rule(strokeDash=[6, 4], color="#A64C40").encode(y=alt.Y("目标:Q", title="还款覆盖倍数（倍）"))
        st.altair_chart((bars + target + values).properties(height=280), alt="各情景还款覆盖倍数，红色虚线为项目安全线1.20倍；柱顶显示实际倍数")
    st.caption(STRESS_HELP)
    st.caption(CASH_GAP_HELP)
    st.caption(plan["repayment_note"])
    st.subheader("风险与可执行建议")
    for item in plan["recommendations"]:
        with st.container(border=True):
            st.markdown("**" + item["title"] + "**")
            st.markdown(item["quantification"])
            st.caption("原因：" + item["reason"])
            st.markdown("**建议：**" + item["action"])
    drivers = run["outputs"]["prepare_deliverables"].get("drivers", [])
    if drivers:
        st.subheader("经营改善能释放多少资金")
        for driver in drivers:
            with st.container(border=True):
                st.markdown("**" + driver["title"] + " · " + fmt(driver["value"], driver["unit"]) + "**")
                st.caption(driver["reason"])
                st.markdown(driver["action"])
    with st.expander("算法、边界与可复核约束"):
        st.markdown("**" + plan["algorithm"]["name"] + "**")
        for objective in plan["algorithm"]["objective"]:
            st.markdown("- " + objective)
        st.caption("已检查候选顶点：" + str(plan["algorithm"]["checked_candidates"]))
        st.dataframe(pd.DataFrame([{"约束": c["label"], "上限": fmt(c["limit"], "元") + ("/12个月" if c["unit"] == "元/年" else ""), "已使用": fmt(c.get("used"), "元"), "剩余空间": fmt(c.get("remaining"), "元")} for c in plan["algorithm"]["constraints"]]), hide_index=True, alt="融资组合求解使用的各渠道容量与共享约束，以及当前解的使用量和剩余空间")
        for assumption in plan["algorithm"]["assumptions"]:
            st.caption(assumption)
    with st.expander("数据桥接与计算口径"):
        for bridge in run.get("derivations", []):
            st.caption(bridge["formula"] + " → " + fmt(bridge["value"], "元"))
        st.caption("手工核验的CFADS优先使用；由经营现金流推导时仅作明确标识的代理口径。只有年度数据时不能据此证明月内现金安全。")


def render_portfolio(run, *, compact=False):
    from finbridge.result_review import build_result_review, money as input_money
    plan = effective_portfolio(run["outputs"])
    if not plan:
        st.info("本历史任务没有融资组合，请重新生成。")
        return
    from finbridge.task_focus_ui import render_task_focus
    render_task_focus(run)
    from finbridge.adjustment import render_adjustment
    render_adjustment(run)
    review = build_result_review(run)
    f = plan["funding"]
    st.subheader("调整前先核对什么")
    hints = {
        "融资组合": "先核实各渠道确实可用的额度、用途和报价，再看未覆盖缺口；修改后必须重新生成。",
        "风险分析": "优先核对年度还款现金、未来12个月已有本息和应收逾期；现金改善试算不能视为已到账。",
        "方案比较": "先明确更看重补足资金、减轻一年内还款还是留出抗压余量；各方案互相替代，不能叠加。",
    }
    st.write(hints[run["goal"]])
    with st.expander("渠道诊断、原始输入与修改入口", expanded=not plan.get("available") or f.get("debt_total") == 0):
        st.subheader("融资组合建议" if run["goal"] == "融资组合" else "融资金额参考与数据核对", icon=":material/pie_chart:")
        st.caption("本次测算结果 · " + run["id"] + " · 依据任务生成时的数据")
        if run["outputs"].get("analyze_industry_region", {}).get("market_decision", {}).get("changed"):
            st.info("本次采用近期证据触发的市场压力组合；基础方案与变化原因可在行业地区详情查看。")
        if not plan["available"] or f.get("debt_total") == 0 and (f.get("gap") or 0) > 0:
            st.warning(review["title"])
        elif (f.get("unfunded_gap") or 0) > 0:
            st.info(review["title"])
        else:
            st.success(review["title"])
        for cause in review["causes"]:
            st.write(cause)
        cols = st.columns(3)
        for col, label, key in zip(cols, ["可配置新增债务", "尚缺用途资金", "另需一次性费用"], ["debt_total", "unfunded_gap", "fees_due"]):
            col.metric(label, fmt(f.get(key), "元"), border=True)
        st.caption("用途预算 " + fmt(f.get("need"), "元") + " − 自有资金 " + fmt(f.get("internal_used"), "元") + " = 原始外部缺口 " + fmt(f.get("gap"), "元"))
        st.markdown("**渠道结果与待核对字段**")
        st.dataframe(pd.DataFrame([{"渠道": r["channel"], "建议本金": fmt(r["amount"], "元"),
            "可用容量": fmt(r["capacity"], "元"), "当前状态": r["status"], "需要核对的字段": r["field"]}
            for r in review["channels"]]), hide_index=True, alt="各融资渠道的结果、零值原因及应核对的原始字段")
        with st.expander("核对本次实际读到的数据与修改位置", expanded=f.get("debt_total") == 0):
            for r in review["channels"]:
                st.write(r["field"] + "：" + input_money(r["raw"]) + " · " + r["source"])
                st.caption("企业与数据 → 档案与财务字段 → " + r["group"] + "；" + r["action"])
            st.write("压力下可分配给新增债务的未来12个月本息：" + fmt(review["service_budget"], "元"))
            st.caption("这是每年可承受的还本付息金额，不是贷款本金上限。")
            st.caption(f"计算依据：年度可用于偿债现金流 {fmt(review['cfads'], '元')}，压力降幅 {review['stress_drop']:.0%}，目标覆盖率 {review['target_dscr']:.2f}，现有年度本息 {fmt(review['existing_service'], '元')}。")
        a, b = st.columns(2)
        if a.button("1. 核对或修改企业数据", key="review_data_"+str(compact)+run["id"], icon=":material/edit:"):
            st.switch_page("app_pages/company.py")
        if b.button("2. 返回工作台重新生成", key="review_rerun_"+str(compact)+run["id"], icon=":material/refresh:"):
            st.switch_page("app_pages/workspace.py")
        st.caption(review["note"])
        if plan.get("available") and (f.get("debt_total") or 0) > 0:
            st.markdown("**优先处理的事项 · 根据本次结果生成**")
            for item in plan.get("recommendations", [])[:2]:
                st.write(item["title"] + "：" + item["action"])
    render_terms()
    if st.toggle("查看完整测算、压力测试与计算依据", key="review_details_"+str(compact)+run["id"]):
        st.caption("以下是本次完整计算结果；算法与使用边界为通用说明。")
        _render_portfolio_details(run, compact=False)
