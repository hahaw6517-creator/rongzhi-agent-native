"""Bounded, dated primary-source research. No corporate accounts leave this module."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import ipaddress
import os
import json
from pathlib import Path
import re
import socket
from urllib.parse import urlencode, urljoin, urlsplit
import xml.etree.ElementTree as ET

import httpx

LPR_INDEX = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html"
WINDOW_DAYS = 90


def primary_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return False
    try:
        p = urlsplit(value)
        host = (p.hostname or "").lower()
        return (p.scheme == "https" and not p.username and not p.password and p.port in (None, 443)
                and (host.endswith(".gov.cn") or host in {"gov.cn", "www.cninfo.com.cn", "www.sse.com.cn", "www.szse.cn"}))
    except ValueError:
        return False


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.links, self.meta = [], [], {}
        self.hidden = 0
        self.link = None
        self.article = []
        self.article_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        void = tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if not void:
            if self.article_depth:
                self.article_depth += 1
            elif tag == "article" or a.get("id", "").lower() in {"zoom", "zoomcon", "ucap-content"} or any(
                    x in a.get("class", "").split() for x in ("TRS_Editor", "article-content")):
                self.article_depth = 1
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "meta":
            self.meta[(a.get("name") or a.get("property") or "").lower()] = a.get("content", "")
        if tag == "a":
            self.link = [a.get("href", ""), ""]

    def handle_endtag(self, tag):
        if self.article_depth and tag not in {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}:
            self.article_depth -= 1
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.link:
            self.links.append(tuple(self.link))
            self.link = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.article_depth:
                self.article.append(data)
            if self.link:
                self.link[1] += data


def parse_date(value):
    if not isinstance(value, str):
        return None
    match = re.search(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", value)
    try:
        if match:
            return date(*map(int, match.groups()))
        return parsedate_to_datetime(value).date()
    except (ValueError, TypeError, OverflowError):
        return None


def safe_get(client, url):
    """Revalidate each redirect and DNS result; stream with a strict size limit."""
    for _ in range(4):
        if not primary_url(url):
            raise ValueError("nonprimary URL")
        addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("nonpublic address")
        with client.stream("GET", url, follow_redirects=False) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                continue
            r.raise_for_status()
            if "html" not in r.headers.get("content-type", ""):
                raise ValueError("not HTML")
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > 1_500_000:
                    raise ValueError("oversized source")
                chunks.append(chunk)
            raw = b"".join(chunks)
            # Chinese official sites occasionally omit the charset header.
            encoding = r.charset_encoding or ("gb18030" if re.search(br"charset\s*=\s*[\"']?gb", raw[:4000], re.I) else "utf-8")
            return raw.decode(encoding, errors="replace"), url
    raise ValueError("redirect limit")


def read_source(candidate, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    try:
        with httpx.Client(timeout=7, trust_env=False, headers={"User-Agent": "FinBridgeResearch/1.0"}) as client:
            raw, url = safe_get(client, candidate["url"])
        page = Page()
        page.feed(raw)
        title = page.meta.get("articletitle") or candidate.get("title", "")
        published = next((page.meta[k] for k in ("pubdate", "publishdate", "publishtime", "article:published_time", "date", "firstpublishedtime") if page.meta.get(k)), "")
        all_text = re.sub(r"\s+", " ", " ".join(page.text)).strip()
        # Visible publication labels outrank CMS build/update timestamps.
        date_match = re.search(r"(?:发布时间|发布日期|时间)\s*[:：]\s*(20\d{2}[-/]\d{1,2}[-/]\d{1,2})", all_text)
        d = (parse_date(date_match[1]) if date_match else None) or parse_date(title) or parse_date(published)
        date_basis = "页面明示发布时间" if date_match else "公告标题完整日期" if parse_date(title) else "页面日期元数据" if d else "未确认"
        article = re.sub(r"\s+", " ", " ".join(page.article)).strip()
        text = (title + " " + article if len(article) >= 50 else all_text)[:18000]
        if len(text) < 100:
            return None
        if candidate.get("category") not in {"macro_lpr", "macro_pmi", "region_statistics"} and not any(
                word in title for word in ("融资", "贷款", "金融", "信贷", "授信", "回款", "订单", "景气", "经济运行", "制造", "资金", "应收", "租赁")):
            return None
        return {"title": title[:200], "url": url, "snippet": text[:800], "content": text,
                "published_at": d.isoformat() if d else "日期未确认", "date_basis": date_basis,
                "retrieved_at": today.isoformat(), "age_days": (today-d).days if d else None,
                "fresh": bool(d and 0 <= (today-d).days <= WINDOW_DAYS),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "evidence_status": "已读取原站正文；政策有效性与企业资格仍需核实", "full_text_verified": True,
                "category": candidate.get("category", "industry_region")}
    except (httpx.HTTPError, ValueError, OSError, LookupError):
        return None


def research_plan(industry, region, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    # Sector aliases broaden overly specific uploaded labels without sending company identities.
    from finbridge.market_rules import sector_knowledge
    kb = sector_knowledge(industry)
    term = kb["search_term"] or industry[:60]
    return [{"topic": "地区金融环境", "query": f"{region[:60]} 金融 信贷 企业 融资 {today.year}", "days": 90},
            {"topic": "行业近期经营", "query": f"{term} 订单 回款 景气 融资 {today.year}", "days": 90},
            {"topic": "同行融资披露", "query": f"{term} 企业 授信 融资 公告 {today.year}", "days": 90}]


def fetch_market_sources(industry, region, *, return_audit=False):
    """Fresh per analysis, bounded parallel reads; optional provider plus free official LPR."""
    plan = research_plan(industry, region)
    candidates = []
    key = os.getenv("TAVILY_API_KEY", "").strip()
    with httpx.Client(timeout=8, trust_env=False, follow_redirects=True) as client:
        # Always available without a search-provider account; actual sites can still deny access.
        try:
            raw, base = safe_get(client, LPR_INDEX)
            page = Page()
            page.feed(raw)
            for href, title in page.links:
                if "LPR" in title and "公告" in title:
                    candidates.append({"url": urljoin(base, href), "title": title, "category": "macro_lpr"})
                    if len(candidates) >= 2:
                        break
        except (httpx.HTTPError, ValueError, OSError):
            pass

        from finbridge.market_rules import sector_knowledge
        indexes = []
        if sector_knowledge(industry)["id"] == "manufacturing":
            indexes.append(("https://www.stats.gov.cn/sj/zxfb/", "采购经理指数运行情况", "macro_pmi", 1))
        registry = json.loads((Path(__file__).resolve().parents[2] / "data/market_source_registry.json").read_text(encoding="utf-8"))
        for entry in registry:
            if entry["region"] in region:
                indexes.append((entry["index_url"], entry["title_keyword"], entry["category"], 2))
        def index_candidates(spec):
            url, keyword, category, limit = spec
            found = []
            try:
                raw, base = safe_get(client, url)
                page = Page()
                page.feed(raw)
                for href, title in page.links:
                    target = urljoin(base, href)
                    if keyword in title and primary_url(target) and target not in {x["url"] for x in found}:
                        found.append({"url": target, "title": title, "category": category})
                        if len(found) >= limit:
                            break
            except (httpx.HTTPError, ValueError, OSError):
                pass
            return found
        with ThreadPoolExecutor(max_workers=3) as pool:
            for found in pool.map(index_candidates, indexes[:4]):
                candidates.extend(found)

        def discover(item):
            found = []
            try:
                if key:
                    r = client.post("https://api.tavily.com/search", headers={"Authorization": "Bearer " + key}, json={
                        "query": item["query"], "time_range": "year" if item.get("days", 90) > 90 else "quarter", "search_depth": "advanced", "max_results": 4,
                        "include_domains": ["gov.cn", "cninfo.com.cn", "sse.com.cn", "szse.cn"], "include_answer": False})
                    r.raise_for_status()
                    if len(r.content) <= 500_000:
                        found = r.json().get("results", [])
                else:
                    r = client.get("https://www.bing.com/search?" + urlencode({"q": item["query"] + (" (site:cninfo.com.cn OR site:sse.com.cn OR site:szse.cn OR site:gov.cn)" if item["topic"] == "同行融资披露" else " site:gov.cn"), "format": "rss"}))
                    r.raise_for_status()
                    if len(r.content) <= 500_000:
                        found = [{"url": node.findtext("link", ""), "title": node.findtext("title", "")}
                                 for node in ET.fromstring(r.content).findall("./channel/item")[:5]]
            except (httpx.HTTPError, ValueError, ET.ParseError):
                pass
            return [{"url": x["url"], "title": str(x.get("title", ""))[:200], "category": item["topic"]}
                    for x in found if isinstance(x, dict) and primary_url(x.get("url"))]

        unique = list({x["url"]: x for x in candidates}.values())[:12]
        with ThreadPoolExecutor(max_workers=4) as pool:
            initial = [x for x in pool.map(read_source, unique) if x]
        from finbridge.research_fallback import staged_research
        today = datetime.now(timezone(timedelta(hours=8))).date()
        result = staged_research(industry, region, today, discover, read_source, initial)
    return result if return_audit else result["sources"]
