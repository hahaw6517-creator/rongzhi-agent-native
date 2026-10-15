"""Inline Streamlit conversation over the same grounded agent as the native website."""
from copy import deepcopy
import pandas as pd
import streamlit as st
from finbridge.config import load_settings
from finbridge.agent import AgentConfigurationError,AgentRequestError
from finbridge.decision_chat import DecisionConversation
from finbridge.workflow import fingerprint


def render_decision_chat(run,location):
    from finbridge.ui import store_run
    sessions=st.session_state.setdefault("decision_conversations",{})
    root=run.get("conversation_id",run["id"])
    chat=sessions.setdefault(root,dict(head_run_id=run["id"],messages=[]))
    settings=load_settings();prefix="finance_chat_"+location+"_"+root
    with st.container(border=True):
        st.subheader("融资决策对话")
        st.caption("基于本企业财报、专业金融算法、历史方案和市场证据。可以在这里解释、试算或采用建议，无需回工作台修改参数。")
        st.caption("当前分析："+run["id"]+" · "+str(run["raw_public"].get("company_name","")))
        if chat["head_run_id"]!=run["id"]:
            st.info("这段对话已有较新的分析版本。旧报告仍可查看。")
            if st.button("切换到对话最新版本",key=prefix+"latest"):
                st.session_state.active_run_id=chat["head_run_id"];st.rerun()
            return
        with st.container(height=360,border=False):
            if not chat["messages"]:st.write("可以问：为什么建议这个方案？如果改成更少金额、更长期限会怎样？近期市场变化是否影响方案？")
            for message in chat["messages"]:
                with st.chat_message(message["role"]):
                    st.text(message["content"])
                    if message.get("model_text_validated") is False:st.warning("模型文字未通过核验，本条只展示金融工具生成的结论。")
                    if message.get("follow_up"):st.info(message["follow_up"])
                    card=message.get("card")
                    if card:
                        st.caption(card["title"]+" · "+card["run_id"])
                        a,b=st.columns(2);a.metric("外部借款需求",card["requested"]);b.metric("建议拟申请",card["proposed"])
                        a,b=st.columns(2);a.metric("需调整支出",card["gap"]);b.metric("压力覆盖倍数",card["coverage"])
                        st.caption(card["verification"].get("status","未验证"))
                        if card.get("comparison"):st.dataframe(pd.DataFrame(card["comparison"]).rename(columns={"label":"变化项目","before":"之前","after":"本轮","delta":"变化"}),hide_index=True,alt="对话重算前后的真实量化对比")
                        if card.get("metrics"):st.dataframe(pd.DataFrame([{ "指标":x["label"],"结果":x["display"],"公式":x["formula"]} for x in card["metrics"]]),hide_index=True,alt="对话解释指标及公式")
                        if card.get("strategies"):
                            with st.expander("金融算法实际求解的策略对比"):
                                st.dataframe(pd.DataFrame(card["strategies"]).rename(columns={"title":"策略","proposed":"拟申请","gap":"需调整支出","interest":"假设利息","service":"还款峰值","coverage":"抗压倍数","reason":"取舍原因"}),hide_index=True,alt="对话调用专业算法比较融资策略")
                    if message.get("tools"):
                        with st.expander("本轮实际工具与来源"):
                            for event in message["tools"]:st.write(event["label"]+" · "+event["status"]);st.json(event["arguments"])
                            for source in message.get("source_references",[]):st.link_button(source["title"],source["url"])
                            market=message.get("market",{})
                            st.caption(str(market.get("evidence_note") or "本轮没有新检索，沿用分析证据")+" · "+str(market.get("status") or "未取得市场分析"))
        choice=None
        suggestions=["为什么建议这个融资方案？","如果改成借60万元、36个月还完，重新算一下","采用你已经验证的调整建议","结合近期行业和当地金融环境重新评估"]
        for column,text in zip(st.columns(2),suggestions[:2]):
            if column.button(text,key=prefix+text,disabled=not settings.api_configured):choice=text
        with st.expander("更多对话示例"):
            for text in suggestions[2:]:
                if st.button(text,key=prefix+text,disabled=not settings.api_configured):choice=text
        entered=st.chat_input("例如：改成借60万元、36个月还完，并比较还款压力",key=prefix+"input",disabled=not settings.api_configured,submit_mode="disable",max_chars=2000)
        st.caption("发送后调用原配置模型，按需发送本任务财报、分析和对话。数值由金融算法生成，调整保存为情景版本，不修改财报。")
        if not settings.api_configured:st.info("尚未配置API，对话暂不可用；已有分析仍可查看。")
        question=choice or entered
        if question:
            try:
                if fingerprint(st.session_state.financial_data,{})!=fingerprint(run["raw_public"],{}):raise ValueError("财报已修改，请先生成新分析，再继续对话。")
                agent=DecisionConversation(run,settings,history=chat["messages"],versions=list(reversed(st.session_state.runs)))
                with st.status("正在读取本企业分析并按需调用金融工具…",expanded=False) as status:
                    agent.progress=lambda event:st.write(event["label"]+" · "+event["status"])
                    result=agent.respond(question)
                    status.update(label="本轮金融工具与回答已完成",state="complete")
                if fingerprint(st.session_state.financial_data,{})!=fingerprint(run["raw_public"],{}):raise ValueError("财报已变化，本轮调整未保存到旧版本。")
                candidate=result.get("candidate")
                if candidate:
                    candidate["conversation_id"]=root
                    candidate["conversation_adjustment"]=dict(parent_run_id=run["id"],question=question,tools=deepcopy(result["assistant"]["tools"]))
                    st.session_state.profile=deepcopy(candidate["input_profile"])
                    store_run(candidate);chat["head_run_id"]=candidate["id"]
                chat["messages"]=(chat["messages"]+[result["user"],result["assistant"]])[-40:]
                st.rerun()
            except (ValueError,AgentConfigurationError,AgentRequestError) as exc:st.warning(str(exc))
