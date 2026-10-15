"""Public-statement workflow: import, model assumptions, decisions and revisions."""
from copy import deepcopy
import pandas as pd
import streamlit as st
from finbridge.public_data import BLOCKS,META,PUBLIC_LABELS,public_only,public_example
from finbridge.public_finance import public_model,DEFAULTS,LIMITS,public_profile,NEEDED,PURPOSES,ENTERPRISE_TYPES
from finbridge.result_review import money
from finbridge.workflow import DiligenceRun,report_html,report_markdown,delivery_zip,fmt
from finbridge.market_rules import effective_portfolio

PARAM_LABELS={"forecast_growth":"收入增长情景（%）","capex_multiplier":"历史资本开支倍数","reserve_days":"现金留存天数","maintenance_share":"维持性资本开支假设占比（%）","max_leverage":"资产负债率情景上限（%）","target_coverage":"现金覆盖安全线（倍）","assumed_rate":"借款假设年利率（%）","cash_drop":"还款现金压力降幅（%）","rate_up":"利率上行（百分点）"}


def company_page():
    from finbridge.data import load_uploaded_financial_data
    from finbridge.public_template import public_template_xlsx,public_template_csv
    st.title("公开财务报表与数据")
    st.write("第1步：上传财报原值。第2步：到工作台填写借款金额、用途和期限。无需自己算指标或填写银行授信。")
    st.caption("最少13项本期财务原值；两期应收、存货等细项可选，用于增强周转和现金需求分析。企业类型、行业与地区不代表银行认证资格。")
    source,edit=st.tabs(["导入公开报表","分块查看与修改原值"])
    with source:
        st.caption("Excel按资产负债表、利润表、现金流量表分工作表；科目纵向排列，本期、上期金额分列。支持XLSX/XLSM及分块CSV，最多10MB。")
        upload=st.file_uploader("选择公开财务报表模板文件",type=["xlsx","xlsm","csv"])
        if upload:
            try:
                if upload.size>10*1024*1024:raise ValueError("文件超过10MB")
                frame=load_uploaded_financial_data(upload.name,upload.getvalue())
                index=st.selectbox("选择企业及期间",range(len(frame)),format_func=lambda i:str(frame.iloc[i].get("company_name"))+" · "+str(frame.iloc[i].get("report_period")))
                row=public_only(frame.iloc[index].to_dict())
                st.write("识别企业："+str(row.get("company_name"))+" · "+str(row.get("report_period")))
                st.dataframe(pd.DataFrame([{"公开科目":label,"金额（元）":row.get(key)} for key,label in PUBLIC_LABELS.items()]),hide_index=True,alt="公开报表科目纵向预览")
                st.caption("未披露留空，真实零值填0。旧宽表中的内部条件会被排除；本次只保留公开报表科目。")
                if st.button("使用这份公开报表",type="primary"):
                    st.session_state.financial_data=row
                    st.session_state.profile=public_profile(row)
                    st.session_state.data_source="用户上传公开报表 · "+upload.name
                    st.session_state.financial_editor_revision+=1
                    st.rerun()
            except (ValueError,OSError,ImportError) as exc:st.error("导入失败："+str(exc))
        a,b,c=st.columns(3)
        a.download_button("下载分块Excel模板",public_template_xlsx(),"公开财务报表模板.xlsx")
        b.download_button("下载分块CSV模板",public_template_csv(),"公开财务报表模板.csv")
        c.download_button("下载公开格式模拟示例",public_template_xlsx(True),"公开财务报表示例.xlsx")
        st.caption("公开附注为可选项；没有公开的利息明细时，模型明确显示利息假设。当前不直接读取扫描PDF，不需要自行计算CFADS、融资额度或净营运资本。")
        if st.button("载入公开格式模拟案例"):
            st.session_state.financial_data=public_example();st.session_state.profile=public_profile(public_example())
            st.session_state.data_source="模拟公开报表格式";st.session_state.financial_editor_revision+=1;st.rerun()
    with edit:
        raw=public_only(st.session_state.financial_data)
        with st.form("public_statement_editor"):
            updated={}
            for label,key in META.items():updated[key]=st.text_input(label,value=str(raw.get(key) or ""),max_chars=500)
            st.caption("网站金额统一为元；本期为分析年度，上期为比较年度。同一企业和期间保持合并口径一致。只编辑原值，公式由程序计算。")
            editors=[]
            for block,defs in BLOCKS.items():
                st.subheader(block)
                rows=[]
                for key,label,prior,_ in defs:
                    ref=raw.get("public_provenance",{}).get(key,{}) if isinstance(raw.get("public_provenance"),dict) else {}
                    rows.append({"科目":label,"本期（元）":raw.get(key),"上期（元）":raw.get(prior) if prior else None,"公开页码":ref.get("public_reference","")})
                table=pd.DataFrame(rows)
                table["本期（元）"]=pd.to_numeric(table["本期（元）"],errors="coerce");table["上期（元）"]=pd.to_numeric(table["上期（元）"],errors="coerce")
                table.insert(1,"填写要求",["本期必填" if key in NEEDED else "可选，增强分析" for key,_,_,_ in defs])
                edited=st.data_editor(table,hide_index=True,disabled=["科目","填写要求"],key=f"public_editor_{block}_{st.session_state.financial_editor_revision}",alt=block+"本期和上期公开原值")
                editors.append((defs,edited))
            if st.form_submit_button("保存公开报表原值",type="primary"):
                if not updated["company_name"].strip():st.error("请填写企业名称")
                else:
                    result={**updated,"statement_schema":"public-v2","public_provenance":{}}
                    for defs,edited in editors:
                        for i,(key,_,prior,_) in enumerate(defs):
                            row=edited.iloc[i]
                            for destination,column in ((key,"本期（元）"),(prior,"上期（元）")):
                                if destination:
                                    result[destination]=None if pd.isna(row[column]) else float(row[column])
                                    result["public_provenance"][destination]={"public_reference":str(row["公开页码"]),"source":"网站录入公开报表原值"}
                    st.session_state.financial_data=result
                    st.session_state.profile=public_profile(result,st.session_state.profile)
                    st.session_state.data_source="用户录入公开报表原值";st.session_state.financial_editor_revision+=1
                    st.rerun()
        show_quality(public_model(raw,st.session_state.profile))


def show_quality(m):
    if m["available"]:st.success("公开科目已满足模型计算条件；数据真实性仍以公开报告原文为准。")
    else:
        if m["missing"]:st.warning("缺少公开科目："+"、".join(PUBLIC_LABELS.get(k,k) for k in m["missing"]))
        for issue in m["issues"]:st.error(issue)
        for key in m["invalid"]:st.error("金额格式或范围无效："+PUBLIC_LABELS.get(key,key))


def assumption_controls(values,prefix):
    result={}
    for key,label in PARAM_LABELS.items():
        low,high=LIMITS[key]
        scale=100 if key in {"forecast_growth","maintenance_share","max_leverage","assumed_rate","cash_drop","rate_up"} else 1
        result[key]=st.number_input(label,min_value=float(low*scale),max_value=float(high*scale),value=float(values[key]*scale),step=.1 if scale==100 else 1.,key=prefix+key)/scale
    return result


def request_controls(profile,model,prefix):
    st.caption("填写您还需要向外借的钱，已经扣除自行安排的资金；系统不会再扣一遍账上现金。"+("金额是预填参考，请按本次真实需求修改。" if not profile.get("requested_amount") else ""))
    a,b=st.columns(2)
    amount=a.number_input("想借多少钱（万元）",min_value=.01,max_value=1_000_000.,value=float(profile.get("requested_amount") or max(100000,model.get("gap") or 0))/10000,step=10.,key=prefix+"amount")*10000
    months=b.number_input("希望多久还完（月）",min_value=1,max_value=60,value=int(profile.get("requested_months",24)),key=prefix+"months")
    a,b=st.columns(2)
    purpose=a.selectbox("这笔钱用来做什么",PURPOSES,index=PURPOSES.index(profile.get("requested_purpose","经营周转")),key=prefix+"purpose")
    category=b.selectbox("企业服务类型",ENTERPRISE_TYPES,index=ENTERPRISE_TYPES.index(profile.get("enterprise_type","中小微企业")),key=prefix+"type")
    return dict(requested_amount=amount,requested_months=months,requested_purpose=purpose,enterprise_type=category)


def workspace_page():
    from finbridge.config import load_settings
    from finbridge.task_agent import run_task_agent
    from finbridge.ui import store_run,active_run
    data=st.session_state.financial_data;profile=st.session_state.profile;m=public_model(data,{**profile,"requested_amount":profile.get("requested_amount") or 100000.})
    st.title("中小微与科创融资决策 Agent")
    st.write("先看借款需求是否合适，再给拟申请方案；不合适就重新算一版。当前聚焦制造类、软件与信息技术类企业。")
    a,b,c=st.columns(3)
    a.metric("历史财报推导现金缺口",money(m.get("gap")),border=True)
    b.metric("一年可用于还款的现金（估算）",money(m.get("cash")),border=True)
    c.metric("使用步骤","上传 → 填需求 → 看方案",border=True)
    if m["available"]:show_quality(m)
    else:st.caption("财报必填项缺失时会暂停求解；两期营运资本细项未齐时，借款需求分析使用历史经营现金流平稳情景，不补零。")
    with st.form("public_decision_task"):
        st.subheader("第2步：告诉我们您的融资需求")
        request=request_controls(profile,m,"work_request_")
        goal=st.segmented_control("分析重点",["融资组合","风险分析","方案比较"],default="融资组合")
        objective=st.text_area("本次关注的问题",value=profile.get("objective",""),max_chars=2000)
        with st.expander("情景假设 · 与公开事实分开"):
            st.caption("默认增长来自历史同比外推；所有参数均是可调整的情景。调整后模型重新推导需求，不能当作企业内部计划。")
            settings=assumption_controls(m["assumptions"],"work_")
        configured=load_settings()
        ai=st.toggle("启用 AI 自主规划",disabled=not configured.api_configured)
        st.caption("开启后原配置DeepSeek接口选择工具、观察结果、检索近期行业地区资料并解释结论。关闭时也执行同一组公开数据模型和独立验证工具。")
        submitted=st.form_submit_button("生成公开报表决策",type="primary")
    if submitted:
        if not goal:st.error("请选择分析重点");return
        st.session_state.profile=public_profile(data,{**settings,**request,"objective":objective})
        engine=DiligenceRun(data,st.session_state.profile,goal,st.session_state.data_source)
        with st.status("执行公开数据决策工具…",expanded=True) as status:
            def progress(event):st.write(event["label"]+" · "+event["status"])
            result=run_task_agent(engine,configured,progress=progress) if ai else engine.local(progress)
            status.update(label="公开报表决策已完成",state="complete")
        store_run(result);st.rerun()
    run=active_run()
    if run:
        st.caption("最近任务："+run["id"]+" · "+run["goal"])
        a,b=st.columns(2)
        if a.button("查看方案与调整"):st.switch_page("app_pages/solutions.py")
        if b.button("查看分析报告"):st.switch_page("app_pages/delivery.py")
    if st.button("导入或核对公开报表"):st.switch_page("app_pages/company.py")


def render_request_review(review,report=False):
    st.subheader("先看结论：这笔借款合适吗")
    (st.success if review.get("reasonable") else st.warning)(review["status"])
    st.caption(f"您想借{money(review['requested_amount'])}，用于{review['purpose']}，希望{review['requested_months']}个月还完。")
    for reason in review["reasons"][:3]:st.write(reason)
    alt=review.get("alternative")
    if alt:
        st.subheader("重新求解后的调整方案")
        st.write("**"+alt["title"]+"**："+alt["explanation"])
        a,b,c=st.columns(3);a.metric("调整后拟借",money(alt["amount"]));b.metric("最长还款期",str(alt["months"])+"个月");c.metric("先缩减或延后的支出",money(alt["reduce_or_defer"]))
        if alt["composition"]:st.dataframe(pd.DataFrame([{"候选渠道":c["name"],"拟申请":money(c["amount"]),"期限（月）":c["months"]} for c in alt["composition"]]),hide_index=True,alt="重新求解后的替代融资方案")
        (st.success if alt.get("verified") else st.warning)("调整方案已独立复算，产品准入仍待确认" if alt.get("verified") else "目前没有通过压力验证的新增债务方案")
    if not report:
        with st.expander("为什么这样判断：需求复审明细"):
            st.dataframe(pd.DataFrame([{"检验":"✓ "+c["label"] if c["passed"] else "待处理："+c["label"],"说明":c["detail"]} for c in review["checks"]]),hide_index=True,alt="需求、用途、杠杆和现金压力匹配复审")


def decision_summary(run,report=False):
    from finbridge.sme_decision import recommended_portfolio
    out=run["outputs"];p=recommended_portfolio(out);m=run["public_analysis"];focus=out["prepare_deliverables"]["task_focus"]
    st.subheader("本次在分析什么")
    st.write({"融资组合":"识别下一年度现金缺口，安排不同期限的借款预算。","风险分析":"找出现金与到期压力，计算安全余量并验证改善路径。","方案比较":"比较补足资金、减轻近期还款、提高抗压余量的不同取舍。"}[run["goal"]])
    st.caption(str(run["raw_public"].get("company_name"))+" · "+str(run["raw_public"].get("report_period"))+" · "+run["goal"])
    if p.get("sme_basis"):
        render_request_review(out.get("review_financing_request",p["request_review"]),report)
        st.info(p["sector_model"]["label"]+"。"+p["sector_model"]["interpretation"])
    st.info(focus["summary"])
    st.caption("借款需求由您填写；还款现金与覆盖倍数来自财报估算。拟申请金额未获银行承诺，利率是假设，费用未纳入。" if p.get("sme_basis") else "本页所有融资需求与还款倍数均为公开数据情景估算；利率是假设，费用未纳入。")
    if not p["available"]:
        if not m["available"]:show_quality(m)
        for issue in p.get("risk_flags",[]):st.warning(issue)
        return
    if run["goal"]=="融资组合":
        a,b,c=st.columns(3);a.metric("您填写的外部借款需求" if p.get("sme_basis") else "自主推导融资缺口",money(p["funding"]["gap"]));b.metric("本轮拟申请金额",money(p["funding"]["debt_total"]));c.metric("原需求需调整的金额",money(p["funding"]["unfunded_gap"]))
        st.dataframe(pd.DataFrame([{"候选渠道":c["name"],"拟申请金额":money(c["amount"]),"期限（月）":c["months"],"假设年利率":fmt(c["rate"],"%"),"全期限假设利息":money(c["total_interest"])} for c in p["composition"] if c["amount"]>0]),hide_index=True,alt="候选渠道、拟申请金额与假设成本")
    elif run["goal"]=="风险分析":
        risk=focus["risk"];t=risk.get("threshold")
        if t:
            a,b,c=st.columns(3);a.metric("年度现金代理最低需求",money(t["minimum_cash"]));b.metric("下降临界点","已低于安全线" if t["already_below"] else f"{t['cash_drop_limit']:.1%}" if t["cash_drop_limit"] is not None else "不适用");c.metric("压力下需改善现金代理",money(t["cash_improvement"]))
        st.dataframe(pd.DataFrame(risk["ranked"][:3]).rename(columns={"question":"优先问题","level":"程度","reason":"依据"}),hide_index=True,alt="优先处理的风险与依据")
    else:
        compare=focus["comparison"]
        st.dataframe(pd.DataFrame([{"策略":x["title"],"借款预算":money(x["debt"]),"未覆盖缺口":money(x["gap"]),"全期限假设利息（未含费用）":money(x["total_cost"]),"新增还款峰值（12个月）" if p.get("sme_basis") else "一年内新增本息":money(x["new_service"]),"统一压力覆盖倍数（代理）":fmt(x["common_stress_dscr"],"倍")} for x in compare["options"]]),hide_index=True,alt="融资策略的预算、成本和现金压力比较")
        for x in compare["options"]:st.write("**"+x["title"]+"**："+x["reason"])
        for x in compare["duplicates"]:st.caption(x)
    if report:
        if p.get("sme_basis"):
            st.subheader("财务状况，用大白话看")
            st.dataframe(pd.DataFrame(out["assess_risk"].get("plain_summary",[])).rename(columns={"question":"要回答的问题","conclusion":"如何理解","evidence":"财报证据"}),hide_index=True,alt="财务状况的大白话解释")
        st.subheader("历史财报给出的需求参照" if p.get("sme_basis") else "融资需求为什么是这个数")
        bridge=[("资本开支情景",m["capex"]),("已有本息压力代理",m["service"]),("经营净现金赤字",max(0,-m["forecast_ocf"])),("减：正经营净现金情景",-max(0,m["forecast_ocf"])),("减：历史现金可投入代理",-m["freecash"]),("得到：外部现金缺口",m["gap"])]
        st.dataframe(pd.DataFrame([{"推导步骤":label,"金额":money(value)} for label,value in bridge]),hide_index=True,alt="资本开支和偿债用途减去经营与历史现金来源，逐项推导融资需求")
        st.subheader("支撑结论的核心指标")
        keys=("current_ratio","debt_to_asset_ratio","net_profit_margin","receivables_days","inventory_days","cash_conversion_cycle","operating_cash_flow_margin")
        metrics=[out["calculate_ratios"][k] for k in keys if k in out["calculate_ratios"]]
        st.dataframe(pd.DataFrame([{"指标":x["label"],"结果":fmt(x["value"],x["unit"]),"计算公式":x["formula"],"缺失原因":x.get("data_issue") or "—"} for x in metrics]),hide_index=True,alt="公开报表计算出的核心财务指标")
    st.subheader("风险验证结果")
    v=out["prepare_deliverables"].get("recommended_verification",out["verify_decision"])
    (st.success if v["passed"] else st.warning)(v["status"])
    with st.expander("查看独立复算明细"):
        st.dataframe(pd.DataFrame([{"验证项目":c["label"],"结果":"通过" if c["passed"] else "未通过","独立复算值":money(c["value"]),"边界":money(c["limit"])} for c in v["checks"]]),hide_index=True,alt="独立复算的资金和风险约束")
    if p.get("sme_basis"):
        st.caption(p["repayment_note"])
        with st.expander("候选产品的官方依据、申请条件和办理入口"):
            for channel in p["channel_catalog"]:
                if channel["scope_match"]:
                    st.write("**"+channel["name"]+"** · "+channel["status"])
                    st.write(channel["published_terms"])
                    st.caption("需确认："+"；".join(channel["conditions"])+"。核验日期："+channel["checked_on"])
                    st.link_button("查看官方产品信息",channel["url"])
    st.subheader("压力下现金够不够")
    scenarios=[s for s in p["scenarios"] if not report or s["id"] in {"base","double","cash_drop_30"}]
    st.dataframe(pd.DataFrame([{"情景":s["label"],"年度现金代理":money(s["cfads"]),"已有及新增还款峰值（12个月）" if p.get("sme_basis") else "一年内已有及新增本息代理":money(s["existing_annual_service"]+s["new_annual_service"]),"覆盖倍数（代理）":fmt(s["dscr"],"倍"),"达到安全线还需年度现金":money(s["gap_to_target"])} for s in scenarios]),hide_index=True,alt="公开数据现金代理在压力情景下的覆盖情况")
    plot=pd.DataFrame([{"情景":s["label"],"覆盖倍数":s["dscr"],"状态":"达到情景安全线" if s["dscr"]>=p["algorithm"]["target_dscr"] else "未达到情景安全线"} for s in scenarios if s["dscr"] is not None])
    if not plot.empty:
        import altair as alt
        target=p["algorithm"]["target_dscr"]
        base=alt.Chart(plot).encode(x=alt.X("情景:N",sort=None,axis=alt.Axis(labelAngle=0)),y=alt.Y("覆盖倍数:Q",title="现金覆盖倍数（代理）"))
        bars=base.mark_bar().encode(color=alt.Color("状态:N",scale=alt.Scale(domain=["达到情景安全线","未达到情景安全线"],range=["#087F73","#C95A4F"]),legend=None),tooltip=["情景:N",alt.Tooltip("覆盖倍数:Q",format=".2f")])
        labels=base.mark_text(dy=-10).encode(text=alt.Text("覆盖倍数:Q",format=".2f"))
        rule=alt.Chart(pd.DataFrame({"安全线":[target]})).mark_rule(strokeDash=[6,4],color="#A64C40").encode(y=alt.Y("安全线:Q",title="现金覆盖倍数（代理）"))
        st.altair_chart((bars+rule+labels).properties(height=220),alt="压力情景下的现金代理覆盖倍数；虚线为本次情景安全线，柱顶显示倍数")
        st.caption(f"虚线为本次设定的{target:.2f}倍安全线；柱子是各情景覆盖倍数，绿色达到、红色未达到。不是银行统一标准。")
    st.caption("CFADS通常不是公开报表现成科目，这里由经营现金外推减维持性资本开支假设得到代理值；覆盖倍数也含到期本息代理，不能称为真实合同DSCR。缺口不是建议再借的钱。")
    st.subheader("接下来怎么调整")
    gap=p["funding"]["unfunded_gap"]
    st.write("仍有"+money(gap)+"现金用途未覆盖，可试算减少资本开支、降低增长占款或延后支出；不能默认追加债务。" if gap>.01 else "当前情景下现金用途已覆盖；保持现金余量，核对实际合同与报价后再采用。")
    ctx=out.get("analyze_industry_region",{})
    st.subheader("近期市场对本次决策的影响")
    st.write(ctx.get("market_decision",{}).get("action",ctx.get("summary","本次未检索近期资料")))
    st.caption(ctx.get("source_status","没有可核验资料"))
    with st.expander("行业地区详情与引用"):
        from finbridge.industry_context_ui import render_industry_context
        render_industry_context(run,compact=True)
    with st.expander("公开事实、模型公式和情景假设"):
        st.json(m["assumptions"])
        st.dataframe(pd.DataFrame([{"结果":e["label"],"数值":fmt(e["value"],"%") if e["key"]=="growth" else money(e["value"]),"公式":e["formula"],"来源":"、".join(e["sources"]),"类型":e["kind"]} for e in m["ledger"]]),hide_index=True,alt="公开原值到模型结果的公式与假设追溯")


def solutions_page(run):
    from finbridge.ui import store_run
    st.title("方案与智能对话")
    from finbridge.decision_chat_ui import render_decision_chat
    render_decision_chat(run,"solutions")
    decision_summary(run)
    with st.expander("手动参数（高级，也可直接在上方对话）"):
        with st.form("public_revision_"+run["id"]):
            request=request_controls(run.get("input_profile",{}),run["public_analysis"],"revision_request_"+run["id"])
            values=assumption_controls(run["public_analysis"]["assumptions"],"revision_"+run["id"])
            submitted=st.form_submit_button("重新求解并保存下一版",type="primary")
    if submitted:
        from finbridge.workflow import fingerprint
        if fingerprint(st.session_state.financial_data,{})!=fingerprint(run["raw_public"],{}):
            st.warning("公开原值已经修改，请先用最新报表生成任务，再调整情景。")
            return
        # Historical automatic-demand snapshots remain automatic until a new request is generated.
        revised_profile={**run.get("input_profile",{}),**values,**(request if run.get("input_profile",{}).get("requested_amount") is not None else {})}
        engine=DiligenceRun(run["raw_public"],public_profile(run["raw_public"],revised_profile),run["goal"],run["source"])
        from finbridge.public_revision import attach_saved_evidence
        attach_saved_evidence(engine,run)
        # Offline revision deliberately retains evidence only as context, not an unexecuted AI claim.
        result=engine.local();result["parent_run_id"]=run["id"]
        before=effective_portfolio(run["outputs"])["funding"];after=effective_portfolio(result["outputs"])["funding"]
        result["revision_delta"]={k:after[k]-before[k] if before.get(k) is not None and after.get(k) is not None else None for k in ("gap","debt_total","unfunded_gap")}
        st.session_state.profile=engine.result["input_profile"]
        store_run(result);st.rerun()
    if run.get("parent_run_id"):
        st.caption("上一版："+run["parent_run_id"]+"；本版："+run["id"]+"；执行方式："+run["mode"])
        st.dataframe(pd.DataFrame([{"变化项目":k,"本版减上一版":money(v)} for k,v in run["revision_delta"].items()]),hide_index=True,alt="每版决策的需求、借款与缺口变化")
    history=[r for r in st.session_state.runs if r.get("public_analysis") and r["raw_public"].get("company_name")==run["raw_public"].get("company_name")]
    if len(history)>1:
        chosen=st.selectbox("回看决策版本",[r["id"] for r in history],index=next((i for i,r in enumerate(history) if r["id"]==run["id"]),0))
        if st.button("查看所选版本"):st.session_state.active_run_id=chosen;st.rerun()


def delivery_page(run):
    st.title("公开报表决策报告")
    st.caption("供评审快速了解本次问题、核心数据、风险边界与策略；完整公式和公开来源随报告保存。")
    from finbridge.decision_chat_ui import render_decision_chat
    render_decision_chat(run,"report")
    decision_summary(run,report=True)
    a,b,c=st.columns(3)
    a.download_button("下载可打印决策报告",report_html(run),run["id"]+"-报告.html","text/html")
    b.download_button("下载Markdown报告",report_markdown(run),run["id"]+"-报告.md")
    c.download_button("下载报告与验证证据包",delivery_zip(run,st.session_state.task_checklists[run["id"]]),run["id"]+"-交付.zip")
    with st.expander("全文与完整公开来源"):st.markdown(report_markdown(run))


def execution_page(run):
    st.title("模型、指标与验证证据")
    out=run["outputs"]
    a,b,c=st.tabs(["实际工具调用","财务指标与公式","公开原值与单元格来源"])
    with a:
        for event in run["events"]:
            with st.expander(event["label"]+" · "+event["status"]):st.json(event["result"])
    with b:
        st.dataframe(pd.DataFrame([{"指标":v["label"],"结果":fmt(v["value"],v["unit"]),"公式":v["formula"],"未计算原因":v.get("data_issue") or "—"} for v in out["calculate_ratios"].values()]),hide_index=True,alt="公开财务指标和模型估算的完整公式")
    with c:st.json(run["raw_public"])
