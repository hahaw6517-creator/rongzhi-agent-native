"""Public statement inputs only: no credit limits, budgets or eligible collateral."""
from io import BytesIO
import math
from numbers import Real
import pandas as pd

SCHEMA = "public-v2"
# key, public statement caption, prior-period key, whether negative is meaningful
BLOCKS = {
    "资产负债表": [
        ("total_assets","资产总计","beginning_total_assets",False),
        ("total_liabilities","负债合计",None,False),
        ("current_assets","流动资产合计",None,False),
        ("current_liabilities","流动负债合计",None,False),
        ("ending_equity","所有者权益合计","beginning_equity",True),
        ("cash_and_equivalents","货币资金",None,False),
        ("accounts_receivable","应收账款","beginning_accounts_receivable",False),
        ("inventory","存货","beginning_inventory",False),
        ("accounts_payable","应付账款","beginning_accounts_payable",False),
        ("prepayments","预付款项","beginning_prepayments",False),
        ("advance_receipts","预收款项","beginning_advance_receipts",False),
        ("contract_liabilities","合同负债","prior_contract_liabilities",False),
        ("short_term_debt","短期借款",None,False),
        ("long_term_debt","长期借款",None,False),
        ("current_portion_long_term_debt","一年内到期的非流动负债",None,False),
        ("fixed_assets","固定资产",None,False),
    ],
    "利润表": [
        ("revenue","营业收入","prior_revenue",False),
        ("cost_of_goods_sold","营业成本",None,False),
        ("net_profit","净利润","prior_net_profit",True),
        ("operating_profit","营业利润",None,True),
        ("income_tax_expense","所得税费用",None,True),
        ("selling_expense","销售费用",None,False),
        ("administrative_expense","管理费用",None,False),
        ("research_expense","研发费用",None,False),
        ("finance_expense","财务费用",None,True),
        ("taxes_surcharges","税金及附加",None,False),
    ],
    "现金流量表": [
        ("operating_cash_flow","经营活动产生的现金流量净额","prior_operating_cash_flow",True),
        ("capital_expenditure","购建固定资产、无形资产和其他长期资产支付的现金","prior_capital_expenditure",False),
        ("cash_equivalents_balance","期末现金及现金等价物余额",None,False),
        ("historical_debt_repayment","偿还债务支付的现金",None,False),
        ("net_investing_cash_flow","投资活动产生的现金流量净额",None,True),
        ("net_financing_cash_flow","筹资活动产生的现金流量净额",None,True),
        ("cash_effect_fx","汇率变动对现金及现金等价物的影响",None,True),
        ("opening_cash_equivalents","期初现金及现金等价物余额",None,False),
    ],
    "公开附注（可选）": [
        ("restricted_cash","受限货币资金",None,False),
        ("interest_expense","利息费用",None,False),
        ("depreciation_expense","固定资产折旧",None,False),
        ("amortization_expense","无形资产摊销",None,False),
    ],
}
META = {"企业名称":"company_name","报告期":"report_period","所属行业":"industry","所在地区":"region","公开报告链接或名称":"public_source","上市状态":"listing_status","证券代码":"security_code","上市市场":"listing_market"}
PUBLIC_KEYS = set(META.values()) | {"statement_schema","public_provenance","financial_history","input_contract"}
PUBLIC_LABELS = {}
for block,rows in BLOCKS.items():
    for key,label,prior,signed in rows:
        PUBLIC_KEYS.add(key); PUBLIC_LABELS[key]=label
        if prior:
            PUBLIC_KEYS.add(prior); PUBLIC_LABELS[prior]="上期"+label


def public_only(data):
    """Ignore legacy private fields, even when an old record reaches the new pipeline."""
    result={k:v for k,v in data.items() if k in PUBLIC_KEYS}
    result["statement_schema"]=SCHEMA
    return result


def parse_public_blocks(raw_sheets):
    """Read vertical 科目/本期/上期/unit/source blocks without treating notes as inputs."""
    from finbridge.financial_history import parse_history_sheet
    history=parse_history_sheet(raw_sheets)
    if history is not None:return history
    simple = parse_simple_statement(raw_sheets)
    if simple is not None:return simple
    if "企业信息" not in raw_sheets:
        return None
    meta=raw_sheets["企业信息"].fillna("").values.tolist()
    marker=any(SCHEMA in str(cell) for row in meta[:5] for cell in row)
    if not marker:
        return None
    result={"statement_schema":SCHEMA}; provenance={}
    for row in meta:
        if len(row)>1 and str(row[0]).strip() in META:
            result[META[str(row[0]).strip()]]=str(row[1]).strip()
    if not result.get("company_name") or result["company_name"]=="请填写企业名称":
        raise ValueError("请填写公开报表所属企业名称")
    if not result.get("report_period"):
        raise ValueError("请填写报告期，例如2025年度")
    for block,defs in BLOCKS.items():
        if block not in raw_sheets:
            continue
        raw=raw_sheets[block].fillna("").values.tolist()
        found=set()
        by_label={row[1]:row for row in defs}
        for index,row in enumerate(raw,1):
            if not row or str(row[0]).strip() not in by_label:
                continue
            key,label,prior,signed=by_label[str(row[0]).strip()]
            if key in found:
                raise ValueError("重复科目："+label)
            found.add(key)
            unit=str(row[3]).strip() if len(row)>3 else "元"
            if unit not in {"元","万元","亿元"}:
                raise ValueError(label+"的单位应为元、万元或亿元")
            factor={"元":1,"万元":10000,"亿元":1e8}[unit]
            for col,destination in ((1,key),(2,prior)):
                if not destination or len(row)<=col:
                    continue
                value=row[col]
                if value in ("", "—", "-", "未披露"):
                    result[destination]=None;continue
                try:
                    text=str(value).strip().replace(",", "").replace("，", "")
                    num=float('-'+text[1:-1] if text.startswith('(') and text.endswith(')') else text)*factor
                except (ValueError,TypeError):
                    raise ValueError(label+"含无法识别的金额") from None
                if isinstance(value,bool) or not math.isfinite(num) or abs(num)>1e15 or (num<0 and not signed):
                    raise ValueError(label+"金额范围无效")
                result[destination]=num
                provenance[destination]={"sheet":block,"cell":("B" if col==1 else "C")+str(index),"public_reference":str(row[4]) if len(row)>4 else "未填写页码","unit":unit}
    result["public_provenance"]=provenance
    return pd.DataFrame([result])


def parse_simple_statement(raw_sheets):
    """Single sheet, exactly 类别 / 科目 / 数值. Third column is numeric input."""
    captions={}
    signed_keys=set()
    for block,defs in BLOCKS.items():
        for key,label,prior,signed in defs:
            captions[label]=key
            if signed:signed_keys.add(key)
            if prior:
                captions["上期"+label]=prior
                if signed:signed_keys.add(prior)
    for sheet,frame in raw_sheets.items():
        rows=frame.fillna("").values.tolist()
        if not rows or len(rows[0])<3 or rows[0][0]!="类别" or rows[0][1]!="科目":continue
        result={"statement_schema":SCHEMA};provenance={};unit="元";seen=set()
        for row in rows[1:]:
            if len(row)>2 and str(row[1]).strip()=="金额单位":unit=str(row[2]).strip() or "元"
        if unit not in {"元","万元","亿元"}:raise ValueError("金额单位须为元、万元或亿元")
        scale={"元":1,"万元":10000,"亿元":1e8}[unit]
        for index,row in enumerate(rows[1:],2):
            if len(row)<3:continue
            label=str(row[1]).strip();value=row[2]
            if label in META:
                result[META[label]]=str(value).strip();continue
            if label in {"金额单位",""}:continue
            if label not in captions:
                if value!="":raise ValueError("无法识别的报表科目："+label)
                continue
            key=captions[label]
            if key in seen:raise ValueError("重复科目："+label)
            seen.add(key)
            if value in ("","—","-","未披露"):
                result[key]=None;continue
            text=str(value).strip().replace(",","").replace("，","")
            try:num=float("-"+text[1:-1] if text.startswith("(") and text.endswith(")") else text)*scale
            except (TypeError,ValueError):raise ValueError(label+"请直接填写报表数值") from None
            if isinstance(value,bool) or not math.isfinite(num) or abs(num)>1e15 or num<0 and key not in signed_keys:
                raise ValueError(label+"金额范围无效")
            result[key]=num
            provenance[key]=dict(sheet=sheet,cell="C"+str(index),unit=unit,public_reference=result.get("public_source","报表原值"))
        if not result.get("company_name") or result["company_name"]=="请填写企业名称":raise ValueError("请填写企业名称")
        if not result.get("report_period"):raise ValueError("请填写报告期")
        result["public_provenance"]=provenance
        return pd.DataFrame([result])
    return None


def public_example():
    # Clearly fictional; every input corresponds to a publicly reportable line.
    return dict(statement_schema=SCHEMA, company_name="华辰制造（公开报表格式模拟）",report_period="2025年度",
        industry="高端制造",region="江苏苏州",public_source="虚构测试数据，不对应真实企业",
        total_assets=12800000,beginning_total_assets=11200000,total_liabilities=5760000,current_assets=4800000,
        current_liabilities=3200000,ending_equity=7040000,beginning_equity=6500000,cash_and_equivalents=1000000,
        accounts_receivable=2200000,beginning_accounts_receivable=1800000,inventory=1200000,beginning_inventory=1000000,
        accounts_payable=900000,beginning_accounts_payable=700000,prepayments=200000,beginning_prepayments=180000,
        advance_receipts=0,beginning_advance_receipts=0,contract_liabilities=150000,prior_contract_liabilities=100000,short_term_debt=350000,long_term_debt=1400000,
        current_portion_long_term_debt=100000,revenue=9600000,prior_revenue=8400000,cost_of_goods_sold=6720000,
        net_profit=768000,prior_net_profit=620000,operating_profit=1060000,income_tax_expense=252000,
        operating_cash_flow=1600000,prior_operating_cash_flow=1450000,capital_expenditure=2600000,
        prior_capital_expenditure=1500000,cash_equivalents_balance=900000,historical_debt_repayment=420000,
        restricted_cash=100000,interest_expense=180000,depreciation_expense=500000,amortization_expense=100000)
