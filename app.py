"""FinBridge corporate financing diligence workspace."""
import sys
from pathlib import Path
import streamlit as st
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from finbridge.config import load_settings
from finbridge.ui import initialize

st.set_page_config(page_title="融智 Agent · 企业财务分析与融资组合", page_icon=":material/account_balance:", layout="wide")
initialize()
st.logo(str(ROOT / "assets" / "brand.svg"), size="large")
navigation = st.navigation({
    "融资工作空间": [
        st.Page("app_pages/workspace.py", title="分析工作台", icon=":material/space_dashboard:", default=True),
        st.Page("app_pages/company.py", title="企业与数据", icon=":material/domain:", url_path="company"),
        st.Page("app_pages/execution.py", title="财务分析", icon=":material/account_tree:", url_path="execution"),
        st.Page("app_pages/solutions.py", title="方案与调整", icon=":material/query_stats:", url_path="solutions"),
        st.Page("app_pages/delivery.py", title="分析报告", icon=":material/folder_open:", url_path="delivery"),
    ],
    "知识与方法": [st.Page("app_pages/knowledge.py", title="知识与方法", icon=":material/library_books:", url_path="knowledge")],
}, expanded=True)
with st.sidebar:
    st.space("medium")
    with st.container(border=True):
        st.caption("当前分析对象")
        st.markdown("**" + str(st.session_state.financial_data.get("company_name", "未命名企业")) + "**")
        st.caption(str(st.session_state.financial_data.get("report_period", "未提供报告期")))
        st.badge("模拟数据" if st.session_state.data_source.startswith("模拟") else "用户提供数据", color="orange" if st.session_state.data_source.startswith("模拟") else "blue")
    settings = load_settings()
    st.caption(":material/check_circle: 模型接口已配置" if settings.api_configured else ":material/offline_bolt: 本地工具可用 · 模型未配置")
    st.caption("企业财务分析与融资组合\n\n数据保存在当前浏览器会话，请及时导出分析报告。")
navigation.run()
