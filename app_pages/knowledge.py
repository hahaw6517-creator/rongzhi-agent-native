import streamlit as st

if st.session_state.financial_data.get("statement_schema")=="public-v2":
    from pathlib import Path
    st.title("公开报表决策方法")
    st.markdown((Path(__file__).resolve().parents[1]/"docs/公开报表决策模型说明.md").read_text(encoding="utf-8"))
    st.stop()
from finbridge.workflow import KNOWLEDGE, TOOLS, GOALS
from finbridge.ui import page_header

page_header("FINBRIDGE / KNOWLEDGE & METHODOLOGY", "知识与方法", "了解系统用什么数据、如何得出结论，以及哪些问题仍需人工核验。")
sources, method, examples = st.tabs(["来源知识库", "Agent 方法", "任务示例"])
with sources:
    query = st.text_input("检索融资知识", placeholder="例如：流动资金、应收账款、抵押、租赁")
    docs = [doc for doc in KNOWLEDGE if not query or query.casefold() in " ".join([doc["title"], doc["text"], *doc["tags"]]).casefold()]
    st.caption(f"{len(docs)} 条匹配 · 本地精选摘要 · 来源整理于2026-10-11，不是实时政策订阅")
    for doc in docs:
        with st.container(border=True):
            st.caption(doc["id"] + " / " + doc["scope"])
            st.subheader(doc["title"])
            st.caption(doc["publisher"] + " · 发布日期 " + doc["date"])
            st.markdown(doc["text"])
            st.link_button("打开原始来源", doc["url"], icon=":material/open_in_new:")
    if not docs:
        st.info("没有匹配条目。可尝试“流动资金”或“应收账款”。")
    st.caption("业务适配、组合算法和阈值由本项目演示方法生成。引用监管资料用于解释业务背景，不代表监管机构认可模型结论。")
with method:
    st.subheader("融资组合算法")
    st.markdown("读取报表与未来偿债计划 → 计算36项财务指标 → 确定独立渠道容量 → 枚举可行组合 → 先最大覆盖缺口，再最小化假设利息及费用 → 对同一组合做五情景压力测试。")
    st.caption("决策采用CFADS下降20%、利率上行1个百分点和压力DSCR目标1.20，均为本项目测算假设。容量使用人工核验的可用额度与合格资产；折扣、利率及费用不能据行业名称推定。")
    st.subheader("Agent负责调度，财务算法负责金额")
    st.markdown("**AI 自主规划**：DeepSeek 根据结构化任务选择工具，服务端校验依赖并返回观察结果；模型可根据错误补齐步骤。最多10轮规划、16次工具请求。")
    st.markdown("**行业与地区专项分析**：融资组合求解后，再调用原配置模型，结合行业、地区、财务指标与压力结果分析融资环境、同行常见机制及本企业适配。每次新任务检索近期资料并读取原站正文，90天窗口、引用及适用范围校验后，以知识库规则触发市场压力重算；展示基础/市场组合差异。公开检索仅发送行业与地区；未接入同行统计样本库。")
    st.markdown("**本地工作流**：不调用模型，按预定义流程执行相同的财务工具。API失败时续跑也会明确标记，不会冒充自主规划。")
    for name, (title, dependencies, description) in TOOLS.items():
        with st.expander(title + " · " + name):
            st.markdown(description)
            st.caption("前置依赖：" + ("、".join(dependencies) or "无"))
    st.subheader("数据与风险边界")
    st.markdown("- 数据：虚构案例或用户上传的宽表；统一到元，同企业同期间才合并。\n- 计算：Python计算，保留公式与字段；缺失不补零，金额关系异常暂停压力测试。\n- 规则：五维演示风险筛查，无行业标定，不输出信用评分或审批概率。\n- 知识：精选公开来源＋关键词检索，尚未建设向量知识库或实时产品数据库。\n- 隐私：企业数据仅保存在会话；启用AI才发送到已配置的模型服务。当前无多人权限、持久存储或银行接口。")
with examples:
    cases = [
        ("融资组合", "我们需要300万元经营周转资金，自有资金50万元，请计算各渠道金额、成本、选择理由和压力风险。", "使用制造业案例，设置300万需求、50万自有资金、24个月，执行后查看组合分配、压力情景与完整报告。"),
        ("风险排查", "先检查现金流和短期偿债风险，缺什么资料就生成补充任务。", "载入食品科技承压案例，执行风险排查，查看真实规则触发与优先行动。"),
        ("方案比较", "为设备采购比较融资方式，并测试CFADS下降20%及利率上升1个百分点。", "选择设备购置用途，执行方案比较，查看经营周转用途排除和压力测试。"),
    ]
    for goal, prompt, steps in cases:
        with st.container(border=True):
            st.subheader(goal)
            st.markdown(prompt)
            st.caption(steps)
    st.caption("以上是可复现任务示例。实际结果来自所选企业数据，不预设评审结论。")

with method:
    from finbridge.market_rules import knowledge
    market_kb = knowledge()
    st.subheader("近期市场研究与情景规则")
    st.caption("规则版本 " + market_kb["version"] + "；档位为项目敏感性设计，未经统计校准。没有有效变化时不改变融资金额。")
    for rule in market_kb["rules"]:
        st.write(rule["id"] + " · " + rule["label"])
        st.caption(rule["reason"])
    st.caption("默认可直读央行LPR与制造业PMI，地区官方目录当前含苏州；更广泛检索可配置TAVILY_API_KEY。未取得新资料时报告明确显示证据不足。")
