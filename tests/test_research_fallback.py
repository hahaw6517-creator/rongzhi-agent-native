from datetime import date

from finbridge.research_fallback import applicability, fallback_plan, region_terms, staged_research, validate_peer_references
from finbridge.market_rules import market_decision, normalize_source

TODAY = date(2026, 10, 12)


def document(title, content, category="行业近期经营", **kwargs):
    return normalize_source(dict(title=title, content=content + "测试正文。" * 30,
        url="https://www.suzhou.gov.cn/" + title, published_at="2026-09-28",
        full_text_verified=True, category=category, **kwargs), "CTX-01", TODAY)


def test_known_and_unknown_region_parents_do_not_invent_geography():
    assert region_terms("苏州市吴中区")["province"] == "江苏"
    assert region_terms("未知园区")["province"] == ""
    assert region_terms("未知园区")["alternatives"] == []


def test_each_research_topic_expands_until_qualified_evidence_exists():
    queries = []
    def discover(item):
        queries.append(item)
        if item["topic"] == "地区金融环境" and item["tier"] == 0:
            return [dict(url="https://www.suzhou.gov.cn/local", title="苏州金融")]
        if item["topic"] == "行业近期经营" and item["level"] == "大类行业":
            return [dict(url="https://www.suzhou.gov.cn/sector", title="江苏制造业")]
        if item["topic"] == "同行融资披露" and item["level"] == "替代地区候选":
            return [dict(url="https://www.suzhou.gov.cn/peer", title=item["region_term"] + "制造业企业融资")]
        return []
    def read(c):
        s = document(c["title"], c["title"] + "企业金融信贷运行资料。")
        s["url"] = c["url"]
        return s
    result = staged_research("精密制造", "江苏苏州", TODAY, discover, read)
    assert len(result["sources"]) == 3
    assert [s["applicability"]["level"] for s in result["sources"]] == ["精准资料", "大类行业", "替代地区候选"]
    assert all(x["tier"] == 0 for x in queries if x["topic"] == "地区金融环境")
    assert all("已找到参考" in x for x in result["coverage"].values())
    assert result["sources"][-1]["applicability"]["can_trigger_market_rules"] is False


def test_macro_sources_never_satisfy_all_three_topics_and_exhaustion_is_audited():
    initial = [document("全国LPR", "全国贷款市场报价利率", "macro_lpr")]
    result = staged_research("精密制造", "苏州", TODAY, lambda _: [], lambda _: None, initial)
    assert len(result["audit"]) == 18
    assert all("仍无合格" in x for x in result["coverage"].values())


def test_query_match_cannot_substitute_for_actual_body_or_date_match():
    item = fallback_plan("精密制造", "江苏苏州", TODAY)[0]
    assert applicability(document("北京金融", "北京金融运行"), item, "精密制造", "江苏苏州") is None
    future = document("苏州金融", "苏州金融运行")
    future["age_days"] = -1
    assert applicability(future, item, "精密制造", "江苏苏州") is None


def test_historical_fallback_is_labeled_and_cannot_trigger_parameters():
    item = fallback_plan("精密制造", "江苏苏州", TODAY)[-3]
    source = document("江苏金融", "江苏金融运行")
    source["age_days"] = 180
    match = applicability(source, item, "精密制造", "江苏苏州")
    assert match["level"] == "历史背景"
    assert not match["can_trigger_market_rules"]


def test_proxy_risk_signal_is_rejected_even_if_quote_mentions_target_region():
    quote = "苏州精密制造企业回款周期延长，经营现金流面临压力。"
    source = document("江苏制造业", quote, applicability={"can_trigger_market_rules": False})
    result = market_decision({"revenue": 1e7}, {"industry": "精密制造", "region": "苏州"}, {}, [source],
        [dict(kind="payment_delay", scope="industry", source_id="CTX-01", quote=quote)], TODAY)
    assert not result["changed"]
    assert "仅供参考" in result["rejected_signals"][0]["reason"]


def peer_case():
    quote = "甲制造公司属于精密制造行业，位于江苏苏州，2025年度营业收入960万元，融资用途经营周转。"
    source = document("同行融资披露", quote, "同行融资披露")
    candidate = dict(company_name="甲制造公司", industry="精密制造", region="江苏苏州", period="2025年度",
        purpose="经营周转", source_id="CTX-01", quote=quote)
    return candidate, source


def test_peer_score_requires_quoted_facts_and_scale_period_purpose():
    candidate, source = peer_case()
    data = dict(revenue=9.6e6, report_period="2025年度")
    profile = dict(industry="精密制造", region="江苏苏州", purpose="经营周转")
    result = validate_peer_references([candidate], [source], data, profile)[0]
    assert result["score"] == 100 and result["revenue_yuan"] == 9.6e6
    assert result["classification"] == "符合项目严格筛选的可比候选"
    candidate["region"] = "江苏无锡"
    assert validate_peer_references([candidate], [source], data, profile) == []


def test_missing_scale_or_different_period_cannot_be_called_highly_comparable():
    candidate, source = peer_case()
    result = validate_peer_references([candidate], [source], dict(report_period="2024年度"),
        dict(industry="精密制造", region="江苏苏州", purpose="经营周转"))[0]
    assert result["classification"] == "替代企业机制参考"
    assert len(result["differences"]) == 2


def test_api_receives_fallback_scope_and_export_preserves_it():
    import json
    from types import SimpleNamespace
    from finbridge.industry_context import SECTIONS, analyze_industry_region, context_markdown
    source = document("江苏制造业", "江苏制造业融资与回款资料。")
    match = dict(level="上级地区", reason="江苏省资料", usage_limit="不可等同苏州本地", can_trigger_market_rules=False)
    source["applicability"] = match
    requests = []
    parsed = {"summary": "使用上级地区资料作参考", "funding_coverage_status": "blocked", "data_gaps": []}
    parsed.update({k: [dict(title="参考范围", analysis="江苏省资料不代表苏州当地情况。", source_ids=["CTX-01"], metric_keys=[])] for k in SECTIONS})
    parsed["peers"][0]["analysis"] = "与同行相比，本企业现金缓冲更低。"
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    context = analyze_industry_region({}, dict(industry="精密制造", region="江苏苏州"), {}, client=client, model="test",
        search=lambda *_: dict(sources=[source], audit=[], coverage={"地区金融环境": "上级地区参考"}, plan=[], provider="test"))
    assert context["available"]
    payload = json.loads(requests[0]["messages"][1]["content"])
    assert payload["public_search_excerpts"][0]["applicability"] == match
    assert "分层证据策略" in requests[0]["messages"][0]["content"]
    assert "不可等同苏州本地" in "\n".join(context_markdown(context))
    assert "更低" not in context["sections"]["peers"][0]["analysis"]


def test_official_pmi_is_broad_industry_fallback_and_does_not_cover_peers():
    source = document("全国制造业采购经理指数", "制造业新订单指数运行资料。", "macro_pmi")
    result = staged_research("精密制造", "江苏苏州", TODAY, lambda _: [], lambda _: None, [source])
    assert "已找到参考" in result["coverage"]["行业近期经营"]
    assert "仍无合格" in result["coverage"]["同行融资披露"]
    assert result["sources"][0]["applicability"]["level"] == "大类行业"
    assert not result["sources"][0]["applicability"]["can_trigger_market_rules"]
