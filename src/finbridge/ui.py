"""Shared session helpers and native UI elements."""
from pathlib import Path
from copy import deepcopy
from math import isfinite
from numbers import Real
import pandas as pd
import streamlit as st
from finbridge.workflow import DATA_FIELDS, LABELS, clean_data, fingerprint, fmt
from finbridge.data import FIELD_CATALOG, load_uploaded_financial_data
from finbridge.template import financial_template_xlsx

ROOT = Path(__file__).resolve().parents[2]

@st.cache_data(max_entries=1)
def demo_data():
    from finbridge.public_data import public_example
    first=public_example();weak=dict(first,company_name="现金承压（公开格式模拟）",operating_cash_flow=-200000)
    incomplete=dict(first,company_name="公开资料不全（模拟）",capital_expenditure=None)
    return pd.DataFrame([first,weak,incomplete])

def imported_company_profile(data, previous):
    """Validate a replacement company's needs before either snapshot changes."""
    if data.get("statement_schema") == "public-v2":
        from finbridge.public_ui import public_profile
        return public_profile(data)
    profile = dict(previous)
    if profile.get("objective") == "分析经营周转与偿债能力，计算300万元资金需求的融资组合，并说明金额分配、成本与风险。":
        profile["objective"] = "按所选分析重点，结合下方确认的金额、用途和期限，说明计算结果、主要问题及下一步建议。"
    for source, target in (("financing_need", "amount"), ("available_internal_funds", "internal_funds")):
        value = data.get(source)
        if value is None:
            value = 0.0
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) or not 0 <= value <= 1e15:
            raise ValueError(f"{LABELS[source]}须为0至1000000000000000元之间的有限数值")
        profile[target] = float(value)
    purpose = data.get("purpose") or "经营周转"
    if purpose not in {"经营周转", "订单备货", "设备购置", "综合融资"}:
        raise ValueError("融资用途须为经营周转、订单备货、设备购置或综合融资")
    profile.update(purpose=purpose, industry=data.get("industry") or "未确认", region=data.get("region") or "未确认",
                   collateral="未确认", receivables="未确认")
    return profile

def initialize():
    if st.session_state.get("task_goal") in {"融资准备", "风险排查"}:
        st.session_state.task_goal = {"融资准备": "融资组合", "风险排查": "风险分析"}[st.session_state.task_goal]
    if "financial_data" not in st.session_state:
        st.session_state.financial_data = clean_data(demo_data().iloc[0].to_dict())
        st.session_state.data_source = "模拟案例 · 华辰精密制造"
        st.session_state.profile = {"amount": 3_000_000.0, "internal_funds": 500_000.0, "months": 24,
            "purpose": "经营周转", "assumed_rate": 0.055, "collateral": "未确认", "receivables": "可提供",
            "industry": "高端制造", "region": "江苏苏州", "objective": "按所选分析重点，结合下方确认的金额、用途和期限，说明计算结果、主要问题及下一步建议。"}
        if st.session_state.financial_data.get("statement_schema") == "public-v2":
            from finbridge.public_ui import public_profile
            st.session_state.profile=public_profile(st.session_state.financial_data)
    for key, default in (("runs", []), ("active_run_id", None), ("task_checklists", {}), ("reviewed", {}), ("result_questions", {}), ("financial_editor_revision", 0)):
        st.session_state.setdefault(key, default)
    if st.session_state.financial_data.get("statement_schema") != "public-v2" and demo_data().iloc[0].get("statement_schema") == "public-v2":
        from finbridge.public_data import public_only
        from finbridge.public_finance import public_profile
        st.session_state.financial_data=public_only(st.session_state.financial_data)
        st.session_state.profile=public_profile(st.session_state.financial_data)
        st.session_state.financial_editor_revision+=1

def active_run():
    return next((r for r in st.session_state.runs if r["id"] == st.session_state.active_run_id), None)

def is_stale(run):
    return run["fingerprint"] != fingerprint(st.session_state.financial_data, st.session_state.profile)

def result_guard():
    run = active_run()
    if not run:
        st.info("还没有分析结果。请先上传企业财务数据，再确认需求并生成融资组合。", icon=":material/assignment:")
        if st.button("前往任务工作台", type="primary"):
            st.switch_page("app_pages/workspace.py")
        st.stop()
    if is_stale(run):
        st.warning("企业档案或融资需求已更新。以下为历史快照，请重新执行后使用。", icon=":material/update:")
    st.caption(f"{run['id']}  /  {run['data'].get('company_name', '未命名企业')}  /  {run['created_at'][:16].replace('T', ' ')}  /  {run['mode']}")
    if run.get("model_warning"):
        st.warning(run["model_warning"])
    return run

def page_header(kicker, title, description):
    st.caption(kicker)
    st.title(title)
    st.markdown(description)

def financial_table(data, group=None):
    return pd.DataFrame([{"字段": LABELS.get(f, f), "数值": data[f]*100 if FIELD_CATALOG[f]["unit"] == "%" and data.get(f) is not None else data.get(f), "单位": FIELD_CATALOG[f]["unit"], "填报来源": FIELD_CATALOG[f]["source"], "标准字段": f} for f in DATA_FIELDS if f not in {"financing_need", "available_internal_funds"} and (group is None or FIELD_CATALOG[f]["group"] == group)])

def evidence_table(metrics):
    return pd.DataFrame([{"指标": v["label"], "结果": fmt(v["value"], v["unit"]), "公式": v["formula"],
        "报告期": v["period"], "来源字段": "、".join(LABELS.get(x, x) for x in v["sources"]), "待补充或异常": v["data_issue"] or "—"} for v in metrics.values()])

def store_run(run):
    st.session_state.runs.insert(0, run)
    st.session_state.runs = st.session_state.runs[:12]
    retained = {r["id"] for r in st.session_state.runs}
    for key in ("task_checklists", "reviewed", "result_questions"):
        st.session_state[key] = {k: v for k, v in st.session_state[key].items() if k in retained}
    st.session_state.active_run_id = run["id"]
    st.session_state.task_checklists[run["id"]] = deepcopy(run["outputs"]["prepare_deliverables"]["tasks"])
