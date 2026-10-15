"""Deterministic research expansion; substitute evidence is never a local fact."""
import re
import math
from concurrent.futures import ThreadPoolExecutor

TOPICS = ("地区金融环境", "行业近期经营", "同行融资披露")
PROVINCES = "北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 香港 澳门 台湾".split()
# These are search candidates, not an assertion of equal economic development.
CITY_GROUPS = {
    "江苏": ["苏州", "无锡", "南京", "常州", "南通"],
    "浙江": ["杭州", "宁波", "绍兴", "嘉兴", "温州", "金华", "义乌"],
    "广东": ["广州", "深圳", "佛山", "东莞", "惠州", "中山", "珠海"],
    "山东": ["济南", "青岛", "烟台", "潍坊"],
    "福建": ["福州", "厦门", "泉州", "漳州"],
    "四川": ["成都", "绵阳", "德阳"],
    "湖北": ["武汉", "宜昌", "襄阳"],
    "湖南": ["长沙", "株洲", "湘潭"],
    "安徽": ["合肥", "芜湖", "滁州"],
}


def region_terms(region):
    province = next((p for p in PROVINCES if p in region), "")
    city = next((c for cities in CITY_GROUPS.values() for c in cities if c in region), "")
    if city and not province:
        province = next(p for p, cities in CITY_GROUPS.items() if city in cities)
    explicit_city = re.search(r"([^省自治区]{2,8}市)", region)
    if not city and explicit_city:
        city = explicit_city[1]
    local = city or region
    parents = list(dict.fromkeys(x for x in (city, province) if x and x != region and x != local))
    alternatives = [c for c in CITY_GROUPS.get(province, []) if c != city][:2]
    return {"local": local, "province": province, "parents": parents, "alternatives": alternatives}


def fallback_plan(industry, region, today):
    from finbridge.market_rules import sector_knowledge
    sector = sector_knowledge(industry)
    broad = sector.get("search_term") or industry
    r = region_terms(region)
    stages = [("精准资料", region, industry, 90),
              ("上级地区", r["province"] or "全国", industry, 90),
              ("大类行业", r["province"] or "全国", broad, 90)]
    alternatives = r["alternatives"] or {
        "manufacturing": ["无锡", "佛山"], "technology": ["杭州", "深圳"],
        "trade": ["宁波", "广州"], "agriculture": ["潍坊", "漳州"],
    }.get(sector["id"], ["全国"])
    stages.extend(("替代地区候选", place, broad, 90) for place in alternatives[:2])
    stages.append(("历史背景", r["province"] or "全国", broad, 365))
    suffixes = {TOPICS[0]: "企业 金融 信贷 融资", TOPICS[1]: "订单 回款 景气",
                TOPICS[2]: "企业 授信 融资 公告 营业收入"}
    return [{"tier": n, "level": level, "topic": topic, "region_term": place,
             "industry_term": term, "days": days,
             "query": f"{place} {term if topic != TOPICS[0] else ''} {suffixes[topic]} {today.year}"}
            for n, (level, place, term, days) in enumerate(stages) for topic in TOPICS]


def applicability(source, item, industry, region):
    """Require matching text, not merely a matching search query."""
    from finbridge.market_rules import sector_knowledge
    text = source.get("title", "") + " " + source.get("content", "")
    r = region_terms(region)
    local = bool(r["local"] and r["local"] in text)
    exact_industry = industry in text
    broad = sector_knowledge(industry).get("search_term", industry)
    industry_match = exact_industry or broad in text
    place = item["region_term"]
    place_match = place == "全国" or place in text or (item["level"] == "精准资料" and local)
    topic = item["topic"]
    relevant = place_match if topic == TOPICS[0] else industry_match and (place_match if topic == TOPICS[2] else True)
    if not relevant or not source.get("full_text_verified"):
        return None
    age = source.get("age_days")
    if age is None or age < 0 or age > item["days"]:
        return None
    level = item["level"]
    if age > 90:
        level = "历史背景"
    direct = level == "精准资料" and local and (exact_industry or topic == TOPICS[0])
    if not direct and level == "精准资料":
        level = "大类行业"
    limitations = ("可用于本地区或细分行业分析，仍须核实企业资格。" if direct else
                   "仅作替代参考；不能视为本地区、本细分行业的直接事实，不能直接改变融资额度或压力参数。")
    if topic == TOPICS[2]:
        limitations += "企业规模、资金用途、财务期间须另核实；未核实前不构成高相似度对标。"
    if level == "替代地区候选":
        limitations += "地理接近或行业聚集仅用于选取候选；经济水平相近尚未核实。"
    return {"level": level, "topic": topic, "reference_region": place,
            "reference_industry": item["industry_term"], "local_match": local,
            "exact_industry_match": exact_industry, "can_trigger_market_rules": direct and topic != TOPICS[2],
            "reason": f"正文匹配地区={place}；行业={'细分' if exact_industry else '大类或待核实'}；资料距今{age}天",
            "usage_limit": limitations}


def staged_research(industry, region, today, discover, read, initial=()):
    """At most 18 queries / 36 new pages. Each topic falls back independently."""
    plan = fallback_plan(industry, region, today)
    sources = list(initial)
    for source in sources:
        source.setdefault("applicability", {"level": "宏观或地区经济背景", "topic": "背景补充",
            "reference_region": "以正文范围为准", "reference_industry": "以正文范围为准",
            "can_trigger_market_rules": False, "reason": "来自官方索引的补充资料，尚未通过细分行业与当地金融环境匹配",
            "usage_limit": "用于解释背景，不能据此声称已取得当地信贷环境或同规模同行样本；央行LPR另按专用规则核验。"})
    seen = {s["url"] for s in sources}
    covered, audit = set(), []
    for source in sources:
        text = source.get("title", "") + " " + source.get("content", "")
        if source.get("category") == "macro_pmi":
            item = next(p for p in plan if p["level"] == "大类行业" and p["topic"] == TOPICS[1])
            item = {**item, "region_term": "全国"}
        elif source.get("category") == "region_statistics" and any(k in text for k in ("贷款", "信贷", "金融", "融资")):
            item = plan[0]
        else:
            continue
        match = applicability(source, item, industry, region)
        if match:
            source["applicability"] = match
            covered.add(item["topic"])
            audit.append({**item, "query": "官方栏目直读：" + source.get("title", ""),
                          "found": 1, "accepted": 1, "status": "取得官方参考"})
    pages = 0
    def discover_safely(item):
        try:
            return discover(item)
        except Exception:
            return []
    for tier in sorted({p["tier"] for p in plan}):
        items = [p for p in plan if p["tier"] == tier and p["topic"] not in covered]
        with ThreadPoolExecutor(max_workers=3) as pool:
            batches = list(pool.map(discover_safely, items))
        for item, found in zip(items, batches):
            accepted = 0
            pending = []
            for candidate in found[:4]:
                if candidate["url"] in seen or pages >= 36:
                    continue
                seen.add(candidate["url"])
                pages += 1
                pending.append(candidate)
            with ThreadPoolExecutor(max_workers=4) as pool:
                fetched = list(pool.map(read, pending))
            for source in fetched:
                if not source:
                    continue
                match = applicability(source, item, industry, region)
                if match:
                    source["applicability"] = match
                    sources.append(source)
                    accepted += 1
            if accepted:
                covered.add(item["topic"])
            audit.append({**item, "found": len(found), "accepted": accepted,
                          "status": "取得可引用参考" if accepted else "无合格正文，继续扩大检索"})
        if len(covered) == len(TOPICS):
            break
    # Reserve actual topic evidence before macro supplements; preserve at most 16 sources.
    sources.sort(key=lambda s: (not bool(s.get("applicability")), not s.get("fresh", False)))
    return {"sources": sources[:16], "audit": audit, "plan": plan,
            "coverage": {topic: "已找到参考，适用层级见来源" if topic in covered else "检索各层级后仍无合格资料" for topic in TOPICS},
            "provider": "Tavily" if __import__("os").getenv("TAVILY_API_KEY", "").strip() else "免费Bing RSS与官方索引",
            "limits": "最多18次分层检索、36篇新增正文；替代地区经济水平与企业规模未核实前仅作机制参考。"}


def validate_peer_references(candidates, sources, data, profile):
    """Only quoted facts earn similarity points. Score is a project heuristic."""
    from finbridge.market_rules import sector_knowledge
    refs = {s["id"]: s for s in sources}
    result = []
    for candidate in candidates[:8] if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        source = refs.get(candidate.get("source_id"))
        quote = candidate.get("quote")
        if not source or not source.get("full_text_verified") or not isinstance(quote, str) or not 20 <= len(quote) <= 1500 or quote not in source.get("content", ""):
            continue
        facts = {k: str(candidate.get(k) or "")[:100] for k in ("company_name", "industry", "region", "period", "purpose")}
        if not facts["company_name"] or any(v and v not in quote for v in facts.values()):
            continue
        revenue = None
        amount = re.search(r"营业收入[^。；\d]{0,20}([\d,]+(?:\.\d+)?)\s*(亿元|万元|元)", quote)
        if amount:
            revenue = float(amount[1].replace(",", "")) * {"亿元": 1e8, "万元": 1e4, "元": 1}[amount[2]]
            if not math.isfinite(revenue) or revenue <= 0:
                revenue = None
        target_industry = str(profile.get("industry") or data.get("industry") or "")
        sector = sector_knowledge(target_industry)
        exact = bool(facts["industry"] and facts["industry"] == target_industry)
        broad = bool(facts["industry"] and sector["id"] != "general" and sector_knowledge(facts["industry"])["id"] == sector["id"])
        target_region = region_terms(str(profile.get("region") or data.get("region") or ""))
        local = bool(facts["region"] and target_region["local"] in facts["region"])
        province = bool(facts["region"] and target_region["province"] and target_region["province"] in facts["region"])
        target_revenue = data.get("revenue")
        ratio = min(revenue, target_revenue) / max(revenue, target_revenue) if revenue and isinstance(target_revenue, (float, int)) and math.isfinite(target_revenue) and target_revenue > 0 else None
        same_period = bool(facts["period"] and facts["period"] == str(data.get("report_period", "")))
        same_purpose = bool(facts["purpose"] and facts["purpose"] == str(profile.get("purpose", "")))
        score = (35 if exact else 20 if broad else 0) + (20 if local else 8 if province else 0) + (25 * ratio if ratio else 0) + (10 if same_period else 0) + (10 if same_purpose else 0)
        high = exact and local and same_period and same_purpose and ratio is not None and ratio >= .5 and source.get("fresh")
        differences = [name for ok, name in ((exact, "细分行业未完全一致"), (local, "地区未完全一致"), (ratio is not None and ratio >= .5, "规模缺失或收入差异超过一倍"), (same_period, "财务期间未确认一致"), (same_purpose, "资金用途未确认一致")) if not ok]
        result.append({**facts, "source_id": source["id"], "quote": quote, "revenue_yuan": revenue,
                       "score": round(score, 1), "scale_ratio": ratio,
                       "classification": "符合项目严格筛选的可比候选" if high else "替代企业机制参考",
                       "differences": differences, "limit": "相似分为项目启发式权重（行业35、地区20、规模25、期间10、用途10），不代表获批概率；仍须核实融资条款，不能推算行业均值。"})
    return sorted(result, key=lambda x: x["score"], reverse=True)
