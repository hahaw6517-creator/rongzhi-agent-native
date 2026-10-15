"""Real UI interactions, with no paid external model requests."""
from copy import deepcopy

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from finbridge.template import legacy_financial_template_xlsx as financial_template_xlsx



@pytest.fixture(autouse=True)
def historical_ui_cases(monkeypatch):
    """Regression coverage for previously saved inputs; new public UI has its own tests."""
    from finbridge import ui
    from finbridge.data import load_uploaded_financial_data
    from pathlib import Path
    first=load_uploaded_financial_data("历史.xlsx",financial_template_xlsx(True)).iloc[0].to_dict()
    demos=pd.concat([pd.DataFrame([first]),pd.read_csv(Path(ui.ROOT)/"data/demo_diligence.csv").iloc[1:]],ignore_index=True)
    monkeypatch.setattr(ui,"demo_data",lambda:demos.copy())

def _stage_cash_edit(app, value):
    """Supply the editor delta a browser sends when its form is submitted."""
    editor = next(frame for frame in app.dataframe if frame.key and frame.key.startswith("financial_editor_"))
    row = int(editor.value.index[editor.value["标准字段"] == "cash_and_equivalents"][0])
    app.session_state[editor.key] = {"edited_rows": {row: {"数值": value}}, "added_rows": [], "deleted_rows": []}


def _save_company(app):
    next(button for button in app.button if button.label == "保存企业档案").click().run()
    assert not app.exception


def test_task_to_deliverables_and_all_pages():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    assert not app.exception
    assert app.session_state["runs"] == []
    next(b for b in app.button if b.label == "按所选重点生成分析").click().run()
    assert not app.exception
    assert len(app.session_state["runs"]) == 1
    for page in ("execution", "solutions", "delivery", "company", "knowledge"):
        app.switch_page(f"app_pages/{page}.py").run()
        assert not app.exception, page
        if page == "solutions":
            assert any(element.value == "融资组合建议" for element in app.subheader)
        if page == "delivery":
            assert any(element.value == "这次分析在解决什么问题" for element in app.subheader)


def test_missing_data_and_case_switch_mark_stale():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    next(b for b in app.button if b.label == "按所选重点生成分析").click().run()
    app.switch_page("app_pages/company.py").run()
    next(s for s in app.selectbox if s.label == "选择模拟案例").select(2)
    next(b for b in app.button if b.label == "载入模拟案例").click().run()
    assert not app.exception
    app.switch_page("app_pages/delivery.py").run()
    assert not app.exception
    assert any("历史快照" in warning.value for warning in app.warning)
    app.switch_page("app_pages/workspace.py").run()
    next(b for b in app.button if b.label == "按所选重点生成分析").click().run()
    assert not app.exception
    run = app.session_state["runs"][0]
    assert run["outputs"]["prepare_deliverables"]["readiness"] == "待补充关键资料"


def test_material_completion_persists_across_page_switch():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    next(b for b in app.button if b.label == "按所选重点生成分析").click().run()
    app.switch_page("app_pages/delivery.py").run()
    run = app.session_state["runs"][0]
    task = app.session_state["task_checklists"][run["id"]][0]
    app.checkbox(key=run["id"]+task["id"]).check().run()
    assert not app.exception
    app.switch_page("app_pages/workspace.py").run()
    app.switch_page("app_pages/delivery.py").run()
    assert app.session_state["task_checklists"][run["id"]][0]["completed"] is True


def test_manual_edit_survives_save_without_replaying_previous_delta():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.switch_page("app_pages/company.py").run()
    _stage_cash_edit(app, 1_100_000.0)
    _save_company(app)
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 1_100_000.0
    # Saving the refreshed form again must preserve the accepted data.
    _save_company(app)
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 1_100_000.0


def test_loading_another_case_does_not_reapply_previous_company_edits():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.switch_page("app_pages/company.py").run()
    _stage_cash_edit(app, 1_100_000.0)
    _save_company(app)
    next(select for select in app.selectbox if select.label == "选择模拟案例").select(1)
    next(button for button in app.button if button.label == "载入模拟案例").click().run()
    assert not app.exception
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 200_000.0
    _save_company(app)
    assert "青禾" in app.session_state["financial_data"]["company_name"]
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 200_000.0


def test_reimporting_same_company_restores_uploaded_values_without_old_edits():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.switch_page("app_pages/company.py").run()
    _stage_cash_edit(app, 1_100_000.0)
    _save_company(app)
    app.file_uploader[0].upload("原始模拟数据.xlsx", financial_template_xlsx(example=True)).run()
    assert not app.exception
    next(button for button in app.button if button.label == "使用这份企业数据").click().run()
    assert not app.exception
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 1_000_000.0
    _save_company(app)
    assert app.session_state["financial_data"]["cash_and_equivalents"] == 1_000_000.0


@pytest.mark.parametrize("field,value", [("financing_need", -1), ("available_internal_funds", -1), ("financing_need", 1e15 + 1)])
def test_invalid_uploaded_needs_preserve_current_company_and_workspace(field, value):
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.switch_page("app_pages/company.py").run()
    before_data = deepcopy(app.session_state["financial_data"])
    before_profile = deepcopy(app.session_state["profile"])
    record = dict(before_data, company_name="不应覆盖原档案的企业", **{field: value})
    app.file_uploader[0].upload("无效需求.csv", pd.DataFrame([record]).to_csv(index=False).encode("utf-8-sig")).run()
    next(button for button in app.button if button.label == "使用这份企业数据").click().run()
    assert not app.exception
    assert any("导入失败" in error.value for error in app.error)
    assert app.session_state["financial_data"] == before_data
    assert app.session_state["profile"] == before_profile
    app.switch_page("app_pages/workspace.py").run()
    assert not app.exception


def test_upload_does_not_inherit_previous_company_budget_and_accepts_losses():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    app.switch_page("app_pages/company.py").run()
    record = {"company_name": "亏损但可导入的企业", "report_period": "2025年度", "net_profit": -100_000}
    app.file_uploader[0].upload("需求待确认.csv", pd.DataFrame([record]).to_csv(index=False).encode("utf-8-sig")).run()
    next(button for button in app.button if button.label == "使用这份企业数据").click().run()
    assert not app.exception
    assert app.session_state["financial_data"]["net_profit"] == -100_000
    assert app.session_state["profile"]["amount"] == 0
    assert app.session_state["profile"]["internal_funds"] == 0
    app.switch_page("app_pages/workspace.py").run()
    assert not app.exception


def test_workspace_saves_custom_term_and_supported_large_amount():
    app = AppTest.from_file("../app.py", default_timeout=20).run()
    next(number for number in app.number_input if number.label == "融资期限（月）").set_value(17)
    next(number for number in app.number_input if number.label == "资金需求总额（万元）").set_value(200_000_000.0)
    next(button for button in app.button if button.label == "保存任务需求").click().run()
    assert not app.exception
    assert app.session_state["profile"]["months"] == 17
    assert app.session_state["profile"]["amount"] == 2_000_000_000_000.0
    app.switch_page("app_pages/company.py").run()
    app.switch_page("app_pages/workspace.py").run()
    assert not app.exception


