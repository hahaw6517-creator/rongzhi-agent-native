import streamlit as st
from finbridge.config import load_settings
from finbridge.task_agent import run_task_agent
from finbridge.workflow import DiligenceRun, GOALS, check_data, fmt
from finbridge.ui import page_header, active_run, is_stale, store_run

if st.session_state.financial_data.get("statement_schema") == "public-v2":
    from finbridge.public_ui import workspace_page
    workspace_page()
    st.stop()

page_header("FINBRIDGE / FINANCING ANALYSIS", "用财务数据，算清融资组合。", "上传企业报表和融资条件，量化经营资金占用、债务承受能力与融资金额分配。")
data, profile = st.session_state.financial_data, st.session_state.profile
quality = check_data(dict(data, financing_need=profile["amount"], available_internal_funds=profile["internal_funds"]))
run = active_run()
cols = st.columns(4)
cols[0].metric("本次外部资金缺口", fmt(max(0, profile["amount"] - profile["internal_funds"]), "元"), border=True)
cols[1].metric("财务字段覆盖率", f"{quality['coverage']}%", help=quality["note"], border=True)
cols[2].metric("本次会话执行任务", len(st.session_state.runs), border=True)
cols[3].metric("待办改善建议", sum(not t["completed"] for t in st.session_state.task_checklists.get(run["id"], [])) if run else "—", border=True)
st.space("small")
left, right = st.columns([1.75, 1], gap="large")
with left:
    with st.container(border=True):
        st.subheader("生成企业融资分析", icon=":material/assignment:")
        st.caption("01 上传中文财务数据  →  02 确认资金需求  →  03 计算组合与压力测试")
        with st.form("financing_task"):
            st.caption("融资组合：钱怎么凑；风险分析：哪里扛不住；方案比较：几种借法怎么选。切换后请生成新分析，历史结果不会自动切换。")
            goal = st.segmented_control("分析重点", list(GOALS), default="融资组合", key="task_goal")
            objective = st.text_area("任务说明", value=profile.get("objective", ""), max_chars=2000, height=86,
                                     help="可说明关注点；金额、期限、用途以以下结构化字段为准。")
            a, b = st.columns(2)
            amount = a.number_input("资金需求总额（万元）", min_value=0.0, max_value=1e11, value=float(profile["amount"] / 10000), step=10.0)
            funds = b.number_input("可用自有资金（万元）", min_value=0.0, max_value=1e11, value=float(profile["internal_funds"] / 10000), step=10.0)
            a, b = st.columns(2)
            months = a.number_input("融资期限（月）", min_value=1, max_value=120, value=int(profile["months"]), step=1)
            purposes = ["经营周转", "订单备货", "设备购置", "综合融资"]
            purpose = b.selectbox("资金用途", purposes, index=purposes.index(profile["purpose"]))
            rate = st.number_input("未填写渠道报价时的假设年利率（%）", min_value=0.0, max_value=100.0, value=float(profile["assumed_rate"]*100), step=0.1)
            st.caption("各渠道优先采用上传的利率、期限、费用和融资比例。综合融资须在数据中拆分经营周转与设备用途预算。")
            settings = load_settings()
            use_ai = st.toggle("启用 AI 自主规划", value=False, disabled=not settings.api_configured,
                               help="模型根据任务选择工具并观察执行结果。关闭时使用本地固定工作流。")
            st.caption("启用 AI 后，将当前企业数据与需求发送到原配置模型，并执行行业地区近期检索、正文核验与市场情景重算；公开检索仅发送行业与地区。关闭时不调用模型或联网检索。")
            a, b = st.columns(2)
            submitted = a.form_submit_button("按所选重点生成分析", type="primary", icon=":material/play_arrow:", width="stretch")
            saved = b.form_submit_button("保存任务需求", icon=":material/save:", width="stretch")
        if saved or submitted:
            st.session_state.profile.update(amount=amount*10000, internal_funds=funds*10000, months=months, purpose=purpose, assumed_rate=rate/100, objective=objective)
            if saved:
                st.toast("任务需求已保存")
                st.rerun()
            if not goal:
                st.error("请先选择任务目标。")
            else:
                try:
                    engine = DiligenceRun(data, st.session_state.profile, goal, st.session_state.data_source)
                    with st.status("正在分析财务数据并计算融资组合…", expanded=True) as status:
                        seen = set()
                        def progress(event):
                            identifier = event["step"]
                            if identifier not in seen:
                                st.write((":material/check_circle: " if event["status"] == "完成" else ":material/error: ") + event["label"] + f" · {event['duration_ms']:.1f} ms")
                                seen.add(identifier)
                        result = run_task_agent(engine, settings, progress=progress) if use_ai else engine.local(progress)
                        status.update(label="融资分析与组合计算已完成", state="complete", expanded=False)
                    store_run(result)
                    st.rerun()
                except (ValueError, TypeError) as error:
                    st.error("任务未启动：" + str(error))
with right:
    with st.container(border=True):
        st.subheader("当前企业档案", icon=":material/domain:")
        st.markdown("**" + str(data.get("company_name", "未命名企业")) + "**")
        st.caption(f"{profile.get('industry', '未确认行业')} · {profile.get('region', '未确认地区')} · {data.get('report_period', '未提供报告期')}")
        st.badge("模拟案例" if st.session_state.data_source.startswith("模拟") else "用户数据", color="orange")
        if quality["blocked"]:
            st.warning("存在数据异常，系统将生成核对任务。")
        elif quality["core_missing"]:
            st.warning("基础财务字段不全，先补齐报表。")
        else:
            st.caption(":material/check_circle: 基础字段齐备 · 待核验真实性")
        if st.button("管理企业数据", icon=":material/arrow_forward:", width="stretch"):
            st.switch_page("app_pages/company.py")
    with st.container(border=True):
        st.subheader("一次任务，四份成果")
        st.markdown(":material/fact_check: **风险诊断**  \n五个维度，附数据证据与规则")
        st.markdown(":material/route: **定量融资组合**  \n各渠道金额、成本及选择理由")
        st.markdown(":material/query_stats: **组合压力测试**  \n五种现金流与利率情景")
        st.markdown(":material/inventory_2: **融资分析报告**  \n计算依据、风险与具体改善建议")

if run:
    st.subheader("最近任务", icon=":material/history:")
    with st.container(border=True):
        delivery = run["outputs"]["prepare_deliverables"]
        a, b = st.columns([3, 1])
        a.markdown(f"**{run['id']} · {run['goal']}**  :green-badge[已完成]")
        a.caption(f"{run['mode']} · {run['data'].get('company_name')} · {run['created_at'][:16].replace('T', ' ')}")
        b.badge(delivery["readiness"], color="orange" if delivery["readiness"] != "可继续组合测算" else "green")
        if is_stale(run):
            st.warning("档案已变更，当前结果为历史快照。")
        for finding in delivery["findings"][:3]:
            st.markdown("- " + finding)
        with st.container(horizontal=True):
            if st.button("查看执行证据", icon=":material/account_tree:"):
                st.switch_page("app_pages/execution.py")
            if st.button("查看融资方案", icon=":material/query_stats:"):
                st.switch_page("app_pages/solutions.py")
            if st.button("打开交付中心", type="primary", icon=":material/folder_open:"):
                st.switch_page("app_pages/delivery.py")
    if len(st.session_state.runs) > 1:
        history = {r["id"]: r for r in st.session_state.runs}
        selected = st.selectbox("切换任务快照", list(history), index=list(history).index(run["id"]),
                                format_func=lambda key: key + " · " + history[key]["goal"] + " · " + history[key]["data"].get("company_name", ""))
        if selected != st.session_state.active_run_id:
            st.session_state.active_run_id = selected
            st.rerun()
else:
    st.caption("36 项财务指标  /  4 个融资渠道  /  5 种组合压力情景  /  金额由约束算法求解")
