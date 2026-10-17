"""Re-solve hypothetical adjustments, preserving the original task and market basis."""
from copy import deepcopy
import math
from numbers import Real
from finbridge.market_rules import effective_portfolio
from finbridge.portfolio import build_financing_portfolio
from finbridge.task_focus import build_task_focus

ADJUSTMENTS = {
    "融资组合": (("internal_funds", "试算自有资金", "万元", 0., 1e15),
                 ("confirmed_credit_limit", "试算已确认可用信用额度", "万元", 0., 1e15)),
    "风险分析": (("cash_flow_available_for_debt_service", "试算年度还款现金", "万元", -1e15, 1e15),
                 ("scheduled_debt_service", "试算已有债务年度本息", "万元", 0., 1e15)),
    "方案比较": (("cash_drop", "试算还款现金下降", "%", .2, .4),
                 ("rate_up", "试算利率上行", "个百分点", .01, .05)),
}


def adjustment_defaults(run):
    stress=(effective_portfolio(run["outputs"]) or {}).get("algorithm", {}).get("planning_stress", {})
    result={}
    for key, *_ in ADJUSTMENTS[run["goal"]]:
        if key in {"cash_drop", "rate_up"}:
            result[key]=stress.get(key, .2 if key=="cash_drop" else .01)
        else:
            value=run["profile"].get(key)
            result[key]=run["data"].get(key) if value in (None, "") else value
    return result


def preview_adjustment(run, changes):
    from finbridge.workflow import DiligenceRun
    spec={row[0]:row for row in ADJUSTMENTS[run["goal"]]}
    if not isinstance(changes, dict) or not changes or set(changes)-set(spec):
        raise ValueError("只能试算当前分析重点允许调整的字段")
    for key,value in changes.items():
        if isinstance(value,bool) or not isinstance(value,Real) or not math.isfinite(value) or not spec[key][3] <= value <= spec[key][4]:
            raise ValueError("试算参数超出范围："+spec[key][1])
    base=effective_portfolio(run["outputs"])
    if not base or not base.get("available"):
        raise ValueError("请先修正基础数据，才能进行调整试算")
    data,profile=deepcopy(run["data"]),deepcopy(run["profile"])
    stress=deepcopy(base["algorithm"]["planning_stress"])
    for key,value in changes.items():
        if key in stress:
            stress[key]=value
        elif key=="internal_funds":
            profile[key]=value
        else:
            data[key]=value
            if key in profile:
                profile[key]=value
    engine=DiligenceRun(data,profile,run["goal"],"假设调整试算")
    for tool in ("inspect_data","calculate_ratios","assess_risk"):
        engine.execute(tool)
    outputs=engine.result["outputs"]
    plan=build_financing_portfolio(engine.data,profile,quality=outputs["inspect_data"],risk=outputs["assess_risk"],planning_stress=stress)
    outputs["optimize_financing_portfolio"]=plan
    focus=build_task_focus(engine.data,profile,outputs,run["goal"],plan)
    return dict(goal=run["goal"], changes=changes, plan=plan, focus=focus,
        delta={key:plan["funding"][key]-base["funding"][key] if plan["funding"].get(key) is not None else None
            for key in ("debt_total","unfunded_gap","fees_due")},
        note="仅按假设重新求解，不调用模型或重新联网；沿用本任务市场压力口径。未保存到企业档案，也未改动原报告；真实采用前须核验现金、额度及还款安排，再更新数据重新生成正式任务。")
