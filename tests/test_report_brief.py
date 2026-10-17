from copy import deepcopy
import pytest
from finbridge.report_brief import build_report_brief
from finbridge.template import SIMULATED_EXAMPLE
from finbridge.workflow import DiligenceRun, report_markdown, report_html


def case(goal, **changes):
    data=deepcopy(SIMULATED_EXAMPLE)
    data.update(changes)
    return DiligenceRun(data,dict(amount=3e6,internal_funds=5e5,months=24,assumed_rate=.055,
        purpose="经营周转",industry="精密制造",region="江苏苏州"),goal,"模拟数据").local()


@pytest.mark.parametrize("goal",["融资组合","风险分析","方案比较"])
def test_report_presents_goal_specific_decision_before_full_audit(goal):
    run=case(goal)
    before=deepcopy(run)
    b=build_report_brief(run)
    assert b["goal"] == goal and b["metrics"] and b["risks"] and b["strategies"]
    assert len(b["scenarios"]) == 3
    assert b["channels"] if goal=="融资组合" else not b["channels"]
    assert b["comparison"] if goal=="方案比较" else b["comparison"] is None
    md=report_markdown(run)
    assert md.index("本次分析速览") < md.index("附录：完整计算") < md.index("## 财务证据")
    assert run == before
    assert "关键指标" in md and "下一步策略" in md


def test_invalid_data_does_not_produce_an_approval_or_cashflow_claim():
    b=build_report_brief(case("融资组合",total_assets=1))
    assert not b["available"]
    assert "暂不能" in b["conclusion"]
    assert b["strategies"][0]["title"] == "先修正输入，再判断借法"
    assert not b["scenarios"]


def test_export_escapes_untrusted_company_text():
    run=case("融资组合",company_name="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in report_html(run)
    assert "&lt;script&gt;" in report_html(run)
