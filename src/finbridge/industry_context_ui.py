"""Display the persisted industry/region model analysis without rerunning it."""
import streamlit as st

from finbridge.industry_context import SECTIONS
from finbridge.workflow import fmt


def render_industry_context(run, *, compact=False):
    context = run.get("outputs", {}).get("analyze_industry_region")
    st.subheader("行业与地区融资分析", icon=":material/public:")
    if not context:
        st.info("本历史任务未包含行业地区分析，请重新生成任务。")
        return
    st.caption(f"{context['industry']} · {context['region']} · {context['status']}")
    if compact:
        st.caption(context.get("source_status", context["summary"]))
        if not st.toggle("查看行业地区分析、检索过程与引用", key="context_details_" + run["id"]):
            return
    decision = context.get("market_decision")
    if decision:
        st.caption("LPR是贷款市场报价利率，只作利率环境参考；PMI是采购经理指数，用于观察行业景气变化，不直接代表本企业业绩。利率上行1个百分点，例如从5%升到6%。")
        render_market_decision(decision)
    if context.get("research_coverage"):
        st.markdown("**资料覆盖与替代范围**")
        for topic, coverage in context["research_coverage"].items():
            st.caption(topic + "：" + coverage)
        st.caption(context.get("search_provider", "") + " · " + context.get("research_limits", ""))
    for peer in context.get("peer_references", []):
        with st.container(border=True):
            st.write(peer["company_name"] + " · " + peer["classification"])
            st.caption(f"相似分 {peer['score']}/100 · 来源 {peer['source_id']} · " + ("；".join(peer["differences"]) or "行业、地区、规模、期间和用途匹配"))
            st.caption(peer["limit"])
    if context.get("research_steps"):
        with st.expander("研究过程与证据校验", expanded=False):
            for step in context["research_steps"]:
                st.write(step["step"] + " · " + step["status"])
                st.caption(step["detail"])
            for query in context.get("research_plan", []):
                st.caption(query["topic"] + "：" + query["query"])
    if not context["available"]:
        st.info(context["summary"])
        for source in context.get("sources", []):
            st.link_button(source["id"] + " · " + source["title"], source["url"])
            st.caption(source["published_at"] + " · " + source["evidence_status"])
        return
    if context.get("financial_anchor"):
        st.info(context["financial_anchor"])
    st.write(context["summary"])
    st.caption(context.get("source_status", "") + " · 同行观察不构成统计对标")
    with st.expander("查看行业、地区、同行与融资建议", expanded=not compact):
        for key, title in SECTIONS.items():
            st.markdown("**" + title + "**")
            for item in context["sections"].get(key, []):
                with st.container(border=True):
                    st.write(item["title"])
                    st.write(item["analysis"])
                    evidence = []
                    for metric_key in item["metric_keys"]:
                        metric = run["outputs"]["calculate_ratios"].get(metric_key)
                        if metric:
                            evidence.append(metric["label"] + "：" + fmt(metric["value"], metric["unit"]))
                    st.caption(item["basis"] + ("；财务依据：" + "、".join(evidence) if evidence else "")
                               + ("；资料：" + "、".join(item["source_ids"]) if item["source_ids"] else ""))
        if context.get("data_gaps"):
            st.markdown("**尚缺资料**")
            for gap in context["data_gaps"]:
                st.write("• " + gap)
        for source in context.get("sources", []):
            st.link_button(source["id"] + " · " + source["title"], source["url"], icon=":material/open_in_new:")
            st.caption("原文/条目日期：" + source["published_at"] + "；" + source["evidence_status"])
            if source.get("applicability"):
                match = source["applicability"]
                st.caption(match["level"] + " · " + match["reason"] + " · " + match["usage_limit"])
        st.caption("生成时间：" + context.get("analyzed_at", "未记录") + "；模型：" + context.get("model", "未记录"))
    st.caption(context["boundary"])


def render_market_decision(decision):
    st.markdown("**近期市场证据与融资决策**")
    st.caption(f"分析基准日 {decision['as_of']} · 近{decision['window_days']}天 · {decision['status']} · 证据版本 {decision['evidence_fingerprint']}")
    stress = decision["planning_stress"]
    st.info(f"市场压力情景：CFADS下降{stress['cash_drop']:.0%}，利率上行{stress['rate_up']*100:g}个百分点；DSCR目标{stress['target_dscr']:.2f}。敏感性档位用于安全余量，不是市场预测。")
    import pandas as pd
    st.dataframe(pd.DataFrame([{"指标": r["label"], "基础组合": fmt(r["baseline"], "元"),
                  "市场情景组合": fmt(r["market"], "元"), "变化": fmt(r["delta"], "元")} for r in decision["comparison"]]),
                 hide_index=True, alt="同一企业财务数据在基础与近期市场压力情景下的融资本金、缺口和成本对比")
    st.write(decision["action"])
    with st.expander("查看触发规则、市场组合与压力测试", expanded=decision["changed"]):
        for signal in decision["accepted_signals"]:
            st.write(signal["rule_id"] + " · " + signal["label"] + " · " + signal["source_id"])
            st.write("原文：" + signal["quote"])
            st.caption(signal["reason"])
        for signal in decision["rejected_signals"]:
            st.caption("未采用：" + signal["source_id"] + " · " + signal["reason"])
        for x in decision["lpr_observations"]:
            st.write(f"央行公告 {x['date']}：1年期LPR {x['one_year']:.2%} · {x['source_id']}（非企业报价）")
        plan = decision.get("portfolio", {})
        if plan.get("available"):
            st.dataframe(pd.DataFrame([{"渠道": x["name"], "市场情景本金": fmt(x["amount"], "元"),
                         "企业填报假设利率": fmt(x["rate"], "%")} for x in plan["composition"]]), hide_index=True,
                         alt="市场压力情景重新求解的各渠道融资本金，渠道额度和假设利率仍来自企业输入")
            st.dataframe(pd.DataFrame([{"压力情景": x["label"], "DSCR": x["dscr"],
                         "达目标还需年度现金流": fmt(x["gap_to_target"], "元")} for x in plan["scenarios"]]),
                         hide_index=True, alt="市场情景组合各项压力测试的DSCR与所需额外现金流")
        st.caption(decision["decision_note"])
        for limit in decision["limitations"]:
            st.caption(limit)
