"""Evidence-gated scenario rules and deterministic counterfactual optimization."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re

from finbridge.portfolio import build_financing_portfolio


def knowledge():
    return json.loads((Path(__file__).resolve().parents[2] / "data/market_knowledge.json").read_text(encoding="utf-8"))


def effective_portfolio(outputs):
    """Use the verified market scenario as recommendation; keep baseline immutable."""
    decision = (outputs.get("analyze_industry_region") or {}).get("market_decision") or {}
    if decision.get("changed") and decision.get("portfolio", {}).get("available"):
        return decision["portfolio"]
    return outputs.get("optimize_financing_portfolio")


def sector_knowledge(industry):
    return next((x for x in knowledge()["sectors"] if any(k in industry for k in x["keywords"])),
                {"id": "general", "name": "通用企业", "keywords": [industry], "search_term": industry,
                 "exposures": ["经营现金流", "资金用途与偿债匹配"], "metrics": ["dscr"]})


def normalize_source(candidate, source_id, today):
    """Recompute date/freshness; never trust a provider's 'fresh' boolean."""
    from finbridge.market_sources import parse_date
    source = deepcopy(candidate)
    source["id"] = source_id
    d = parse_date(source.get("published_at", ""))
    age = (today-d).days if d else None
    source.update(age_days=age, fresh=age is not None and 0 <= age <= 90,
                  retrieved_at=source.get("retrieved_at") or today.isoformat())
    content = source.get("content", "")
    source["full_text_verified"] = bool(source.get("full_text_verified") and isinstance(content, str) and len(content) >= 100)
    if source["full_text_verified"]:
        source["content"] = content[:18000]
        source["content_hash"] = hashlib.sha256(source["content"].encode()).hexdigest()
        source["evidence_status"] = "已读取原站正文；政策有效性与企业资格仍需核实"
    else:
        source["evidence_status"] = "公开搜索摘要，未核验全文"
        source.pop("content", None)
    return source


def _scope_matches(source, scope, industry, region, quote):
    text = source.get("title", "") + " " + quote
    if scope == "industry":
        kb = sector_knowledge(industry)
        return any(term and term in text for term in [industry, kb["name"], kb["search_term"], *kb["keywords"]])
    if scope == "region":
        terms = [x for x in re.split(r"[省市区县、，, /]+", region) if len(x) >= 2 and x not in {"中国", "全国"}]
        provinces = ("内蒙古", "黑龙江", "新疆", "西藏", "广西", "宁夏", "河北", "山西", "辽宁", "吉林", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "北京", "天津", "上海", "重庆")
        compact = re.sub(r"[省市区县、，, /]", "", region)
        for province in provinces:
            if compact.startswith(province):
                city = compact[len(province):]
                terms.extend([province, city] if len(city) >= 2 else [province])
                break
        return any(term and term in text for term in terms)
    return False


def _positive(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def lpr_observations(sources):
    observations = []
    for s in sources:
        if not (s.get("fresh") and s.get("full_text_verified") and s.get("category") == "macro_lpr"
                and (s.get("url", "").startswith("https://www.pbc.gov.cn/"))):
            continue
        # Only the announcement's main sentence, not navigation/footer recommendations.
        text = s.get("content", "")
        match = re.search(r"1\s*年期\s*LPR\s*为\s*(\d+(?:\.\d+)?)\s*[%％]", text, re.I)
        if match and 0 <= float(match[1]) <= 20:
            observations.append({"source_id": s["id"], "date": s["published_at"], "one_year": float(match[1])/100})
    return sorted(observations, key=lambda x: x["date"], reverse=True)


def market_decision(data, profile, outputs, sources, signals, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    kb = knowledge()
    sources = [normalize_source(s, s["id"], today) for s in sources]
    base = outputs.get("optimize_financing_portfolio", {})
    rules = {r["kind"]: r for r in kb["rules"]}
    source_by_id = {s["id"]: s for s in sources}
    accepted, rejected = [], []
    if not isinstance(signals, list):
        signals = []
    for raw in signals[:12]:
        if not isinstance(raw, dict):
            continue
        kind, ref, quote = raw.get("kind"), raw.get("source_id"), raw.get("quote")
        rule = rules.get(kind) if isinstance(kind, str) else None
        source = source_by_id.get(ref) if isinstance(ref, str) else None
        reason = None
        if not rule or not source:
            reason = "风险类型或来源不存在"
        elif source.get("applicability", {}).get("can_trigger_market_rules") is False:
            reason = "上级地区、大类行业、替代地区或历史背景仅供参考，不直接触发企业数值调整"
        elif source.get("category") == "同行融资披露":
            reason = "单一同行披露不用于推定整个行业或地区风险"
        elif not source.get("full_text_verified") or not source.get("fresh"):
            reason = "未读取正文、日期未确认、未来日期或超过90天窗口"
        elif not isinstance(quote, str) or not 8 <= len(quote) <= 400 or quote not in source.get("content", ""):
            reason = "证据原句不在已读取正文中"
        elif not any(cue in quote for cue in rule["cues"]):
            reason = "原句未命中知识库中的风险机制"
        elif re.search(r"未(?:出现|发生|见)|没有|并非|不存在|缓解|改善|解决|防范|避免|应对|治理|整治|不得|严禁|风险提示|可能|如果|假如|去年|上年", quote):
            reason = "否定、预防、假设或历史表述不能确认为近期恶化事实"
        elif not _scope_matches(source, raw.get("scope"), str(profile.get("industry", "")), str(profile.get("region", "")), quote):
            reason = "资料与填报行业或地区的适用范围不匹配"
        else:
            gate = rule["financial_gate"]
            value = data.get(gate) if gate == "revenue" else outputs.get("calculate_ratios", {}).get(gate, {}).get("value")
            if not _positive(value):
                reason = "本企业相关财务暴露缺失或为零"
        if reason:
            rejected.append({"kind": kind if isinstance(kind, str) else "未知", "source_id": ref if isinstance(ref, str) else "未知", "reason": reason})
        elif not any(x["kind"] == kind for x in accepted):
            accepted.append({"rule_id": rule["id"], "kind": kind, "label": rule["label"], "source_id": ref,
                             "quote": quote, "scope": raw["scope"], "reason": rule["reason"]})
    baseline_stress = base.get("algorithm",{}).get("planning_stress",{}) if base.get("public_basis") else {}
    base_drop,base_up = baseline_stress.get("cash_drop",.2),baseline_stress.get("rate_up",.01)
    cash_drop, rate_up = base_drop,base_up
    kinds = {x["kind"] for x in accepted}
    for kind in kinds:
        cash_drop = max(cash_drop, rules[kind].get("cash_drop_floor", .2))
        rate_up = max(rate_up, rules[kind].get("rate_up_floor", .01))
    if {"payment_delay", "demand_weakness"} <= kinds:
        cash_drop = max(cash_drop,.3)
    lpr = lpr_observations(sources)
    lpr_delta = None
    if len(lpr) >= 2 and 0 < (date.fromisoformat(lpr[0]["date"])-date.fromisoformat(lpr[1]["date"])).days <= 45:
        lpr_delta = round(lpr[0]["one_year"]-lpr[1]["one_year"], 8)
        rate_up = min(.05, max(rate_up, .01 + max(0, lpr_delta)))
    changed = cash_drop != base_drop or rate_up != base_up
    adjusted = build_financing_portfolio(data, profile, outputs.get("inspect_data", {}), outputs.get("assess_risk", {}),
                planning_stress={"cash_drop": cash_drop, "rate_up": rate_up}) if changed and base.get("available") else deepcopy(base)
    if adjusted and changed:
        adjusted["risk_flags"] = list(dict.fromkeys(base.get("risk_flags", []) + adjusted.get("risk_flags", [])))
        adjusted["algorithm"]["assumptions"].append("市场信号仅触发项目预设敏感性档位，不是对企业未来现金流或银行利率的统计预测。")
    comparable = bool(base.get("available") and adjusted.get("available"))
    comparisons = []
    for key, label in (("debt_total", "组合债务本金"), ("unfunded_gap", "尚未覆盖用途缺口"),
                       ("fees_due", "一次性费用"), ("total_assumed_interest", "全期限假设总利息")):
        b, a = base.get("funding", {}).get(key), adjusted.get("funding", {}).get(key)
        comparisons.append({"key": key, "label": label, "baseline": b, "market": a,
                            "delta": round(a-b, 2) if comparable else None})
    evidence_payload = [{k: s.get(k) for k in ("url", "published_at", "content_hash")} for s in sources]
    fresh = sum(bool(s.get("fresh") and s.get("full_text_verified")) for s in sources)
    status = "近期证据触发市场压力重算" if changed else "已检索，未触发参数调整" if fresh else "近期有效证据不足，沿用基础情景"
    return {"version": kb["version"], "as_of": today.isoformat(), "window_days": 90, "status": status,
            "changed": changed, "fresh_source_count": fresh, "accepted_signals": accepted, "rejected_signals": rejected,
            "planning_stress": {"cash_drop": cash_drop, "rate_up": rate_up, "target_dscr": base.get("algorithm",{}).get("target_dscr",1.2)},
            "lpr_observations": lpr, "lpr_month_change": lpr_delta,
            "evidence_fingerprint": hashlib.sha256(json.dumps(evidence_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
            "comparison": comparisons, "portfolio": adjusted,
            "decision_note": "有近期不利证据时，按预设规则增加安全余量并重算。利好消息不自动增加额度或降低安全底线；同样的输入和证据应得到同样的金额结果。",
            "action": ("按市场压力组合控制新增债务；新增缺口优先分期采购、压缩支出或落实非借款资金，另行筹措费用。"
                       if changed and comparable else "保持基础组合；没有通过校验的市场变化，不为体现时效性而改动金额。"),
            "limitations": ["25%/30%现金流降幅及1.5个百分点利率上行是项目敏感性档位，未经统计校准。",
                            "LPR变动仅影响加息压力情景，不替换已填报利率，也不等于本企业银行报价。",
                            kb["peer_rule"]]}
