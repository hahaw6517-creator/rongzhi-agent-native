import pandas as pd
import streamlit as st
from finbridge.data import FIELD_CATALOG
from finbridge.template import financial_template_xlsx, financial_template_csv
from finbridge.data import load_uploaded_financial_data
from finbridge.workflow import clean_data, check_data, LABELS
from finbridge.ui import page_header, demo_data, financial_table, imported_company_profile

if st.session_state.financial_data.get("statement_schema") == "public-v2":
    from finbridge.public_ui import company_page
    company_page()
    st.stop()

page_header("FINBRIDGE / COMPANY & DATA", "企业与数据", "建立统一的财务数据快照，确认报告期、金额口径和融资条件。")
source_tab, edit_tab = st.tabs(["导入与案例", "档案与财务字段"])
with source_tab:
    left, right = st.columns([1.5, 1], gap="large")
    with left, st.container(border=True):
        st.subheader("导入企业财务数据", icon=":material/upload_file:")
        st.caption("支持 CSV / XLSX / XLSM，单文件最多10MB。每行一家企业；可合并同企业同期间的工作表。")
        upload = st.file_uploader("选择财务表格", type=["csv", "xlsx", "xlsm"])
        if upload is not None:
            try:
                if upload.size > 10*1024*1024:
                    raise ValueError("文件超过10MB")
                frame = load_uploaded_financial_data(upload.name, upload.getvalue())
                row_index = st.selectbox("选择企业及期间", list(range(len(frame))), format_func=lambda i: str(frame.iloc[i].get("company_name")) + " · " + str(frame.iloc[i].get("report_period")))
                st.dataframe(frame.rename(columns=LABELS), hide_index=True, alt="已识别的企业财务记录（中文字段）")
                st.warning("导入将替换当前企业数据，并同步资金需求、自有资金、行业和用途；未填需求金额按0待确认。请确认后重新计算。")
                if st.button("使用这份企业数据", type="primary", icon=":material/check:"):
                    row = clean_data(frame.iloc[row_index].to_dict())
                    profile = imported_company_profile(row, st.session_state.profile)
                    st.session_state.financial_data = row
                    st.session_state.profile = profile
                    st.session_state.data_source = "用户上传 · " + upload.name
                    st.session_state.financial_editor_revision += 1
                    st.rerun()
            except (ValueError, ImportError, pd.errors.ParserError, OSError) as error:
                st.error("导入失败：" + str(error))
        st.caption("金额表头支持元、万元、亿元；无单位默认为元。必须提供明确报告期。不支持扫描PDF或科目在行的复杂财报。")
        with st.container(horizontal=True):
            st.download_button("下载中文 Excel 模板", financial_template_xlsx(), "企业融资分析模板.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")
            st.download_button("下载中文 CSV 模板", financial_template_csv(), "企业融资分析模板.csv", "text/csv", icon=":material/download:")
            st.download_button("下载完整模拟示例", financial_template_xlsx(example=True), "企业融资分析示例.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")
        st.caption("中文模板含填报说明、字段来源和模拟参考。原始报表、未来还本付息计划与融资渠道条件分组列出；未掌握的字段留空，不用0替代未知。")
    with right, st.container(border=True):
        st.subheader("体验三个模拟案例", icon=":material/science:")
        st.caption("完整制造业 / 现金流承压 / 信息不全。所有案例均为虚构数据。")
        demos = demo_data()
        choice = st.selectbox("选择模拟案例", list(range(len(demos))), format_func=lambda i: demos.iloc[i]["company_name"])
        if st.button("载入模拟案例", icon=":material/restart_alt:", width="stretch"):
            row = clean_data(demos.iloc[choice].to_dict())
            profile = imported_company_profile(row, st.session_state.profile)
            st.session_state.financial_data = row
            st.session_state.profile = profile
            st.session_state.data_source = "模拟案例 · " + row["company_name"]
            st.session_state.financial_editor_revision += 1
            st.rerun()
        st.caption("载入后可在“档案与财务字段”调整财务数据及渠道容量，再生成融资组合。")

with edit_tab:
    data, profile = st.session_state.financial_data, st.session_state.profile
    groups = list(dict.fromkeys(v["group"] for v in FIELD_CATALOG.values() if v["unit"] in {"元", "%", "月"}))
    group = st.selectbox("选择数据分组", groups)
    with st.form("company_profile"):
        st.subheader("企业档案与融资条件")
        a, b = st.columns(2)
        name = a.text_input("企业名称", value=str(data.get("company_name", "")), max_chars=100)
        period = b.text_input("报告期", value=str(data.get("report_period") or ""), placeholder="例如：2025年度", max_chars=50)
        a, b = st.columns(2)
        industry = a.text_input("所属行业", value=profile.get("industry", ""), max_chars=100)
        region = b.text_input("所在地区", value=profile.get("region", ""), max_chars=100)
        st.caption("组合容量依据合格债权、未占用担保物、剩余独立信用额度及设备采购金额计算。请在相应分组填写金额与渠道参数。")
        st.caption("金额为元，百分比填5.5表示5.5%，期限为月。先保存当前分组再切换。空值表示未知，0表示确认零。CFADS是每年可用于还本付息的现金，不等于净利润或账上现金余额。")
        table = financial_table(data, group)
        table["数值"] = pd.to_numeric(table["数值"], errors="coerce")
        edited = st.data_editor(table, hide_index=True, disabled=["字段", "单位", "填报来源", "标准字段"], height=450,
            column_config={"数值": st.column_config.NumberColumn(format="%.4f")}, key=f"financial_editor_{group}_{st.session_state.financial_editor_revision}", alt="当前分组可编辑的财务原始字段及填报来源")
        if st.form_submit_button("保存企业档案", type="primary", icon=":material/save:"):
            if not name.strip():
                st.error("请填写企业名称。")
            else:
                data.update({r["标准字段"]: None if pd.isna(r["数值"]) else float(r["数值"])/(100 if r["单位"] == "%" else 1) for _, r in edited.iterrows()})
                data.update(company_name=name.strip(), report_period=period.strip())
                st.session_state.profile.update(industry=industry, region=region)
                st.session_state.data_source = ("模拟案例 · 手动修订" if st.session_state.data_source.startswith("模拟") else "用户提供 · 手动修订")
                st.session_state.financial_editor_revision += 1
                st.toast("企业数据已保存，请重新生成融资组合")
                st.rerun()
    check = check_data(dict(data, financing_need=profile["amount"], available_internal_funds=profile["internal_funds"]))
    st.subheader("数据核验")
    if check["invalid"]:
        st.error("无效字段：" + "、".join(LABELS.get(x, x) for x in check["invalid"]))
    for issue in check["issues"]:
        st.error(issue)
    if check["missing"]:
        st.caption("待补字段：" + "、".join(LABELS.get(x, x) for x in check["missing"]))
    if not check["period_known"]:
        st.warning("报告期尚未确认。")
    if not check["blocked"]:
        st.success("已通过字段与金额关系检查。此检查不核验数据真实性。", icon=":material/check_circle:")
