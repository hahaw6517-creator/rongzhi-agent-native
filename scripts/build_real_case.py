"""Reproduce the built-in case from retained official annual-report text.

Source PDFs are downloaded unchanged; no financial amount is invented.
"""
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from finbridge.data_contract import REQUIRED, LABELS
from finbridge.public_data import BLOCKS

URL25 = 'https://static.haday.com/upload/2026/03/27/e862e415c60546c899815c5a61da233f.pdf'
URL24 = 'https://static.cninfo.com.cn/finalpage/2025-04-03/1222994233.PDF'
pages25 = json.loads((ROOT/'tmp/haitian2025/pages.json').read_text(encoding='utf8'))
pages24 = json.loads((ROOT/'tmp/haitian2024/pages.json').read_text(encoding='utf8'))
# key: (2025 report page, 2024 report page, exact caption without whitespace)
locations = {
 'total_assets': (87,77,'资产总计'),
 'total_liabilities': (88,78,'负债合计'),
 'current_assets': (86,76,'流动资产合计'),
 'current_liabilities': (87,78,'流动负债合计'),
 'ending_equity': (88,78,'所有者权益（或股东权益）合计'),
 'cash_and_equivalents': (86,76,'货币资金'),
 'accounts_receivable': (86,76,'应收账款'),
 'inventory': (86,76,'存货'),
 'accounts_payable': (87,77,'应付账款'),
 'prepayments': (86,76,'预付款项'),
 'contract_liabilities': (87,77,'合同负债'),
 'short_term_debt': (87,77,'短期借款'),
 'current_portion_long_term_debt': (87,78,'一年内到期的非流动负债'),
 'fixed_assets': (86,77,'固定资产'),
 'revenue': (90,81,'其中：营业收入'),
 'cost_of_goods_sold': (90,81,'其中：营业成本'),
 'net_profit': (91,82,'五、净利润（净亏损以“－”号填列）'),
 'operating_profit': (91,82,'三、营业利润（亏损以“－”号填列）'),
 'income_tax_expense': (91,82,'减：所得税费用'),
 'selling_expense': (90,81,'销售费用'),
 'administrative_expense': (90,81,'管理费用'),
 'research_expense': (90,81,'研发费用'),
 'finance_expense': (90,81,'财务费用'),
 'taxes_surcharges': (90,81,'税金及附加'),
 'operating_cash_flow': (94,86,'经营活动产生的现金流量净额'),
 'capital_expenditure': (95,86,'购建固定资产、无形资产和其他长期资产支付的现金'),
 'cash_equivalents_balance': (95,87,'六、期末现金及现金等价物余额'),
 'historical_debt_repayment': (95,86,'偿还债务支付的现金'),
 'net_investing_cash_flow': (95,86,'投资活动产生的现金流量净额'),
 'net_financing_cash_flow': (95,87,'筹资活动产生的现金流量净额'),
 'cash_effect_fx': (95,87,'四、汇率变动对现金及现金等价物的影响'),
 'opening_cash_equivalents': (95,87,'加：期初现金及现金等价物余额'),
 'interest_expense': (91,81,'其中：利息费用'),
 'depreciation_expense': (174,172,'固定资产折旧、油气资产折耗、生产性生物资产折旧'),
 'amortization_expense': (174,172,'无形资产摊销'),
}

def pair(pages, page, caption):
    text = pages[page-1]
    pattern = r'(?m)^\s*' + r'\s*'.join(re.escape(c) for c in caption)
    match = re.search(pattern, text)
    assert match, (page, caption)
    amounts = re.findall(r'-?\d[\d,]*\.\d{2}', text[match.end():match.end()+220])[:2]
    assert len(amounts) == 2, (page, caption, amounts)
    return [float(Decimal(x.replace(',', ''))) for x in amounts]

records = {y: dict(year=y, values={}, provenance={}, source=URL25 if y>=2024 else URL24) for y in (2023,2024,2025)}
for key,(p25,p24,label) in locations.items():
    latest,comparison = pair(pages25,p25,label)
    _,earliest = pair(pages24,p24,label)
    for y,value,page in ((2025,latest,p25),(2024,comparison,p25),(2023,earliest,p24)):
        records[y]['values'][key]=value
        records[y]['provenance'][key]=dict(url=records[y]['source'],page=page,caption=label,unit='元',column='本期' if y==2025 else '上期比较数',verification='官方合并年报原文核对')

# Blank on the face statement is NOT generally zero. Here explicit note 37
# says not applicable, and note 45 confirms all 2025 long loans are current.
assert '□适用 √不适用' in pages25[155] and '37、 预收款项' in pages25[155]
assert '□适用 √不适用' in pages24[153] and '37、 预收款项' in pages24[153]
assert '信用借款 15,000,000.00 49,200,000.00' in pages25[159]
assert '减：一年内到期的长期借款 15,000,000.00 16,000,000.00' in pages25[159]
for y in records:
    records[y]['values']['advance_receipts']=0.0
    records[y]['provenance']['advance_receipts']=dict(url=records[y]['source'],page=156 if y>=2024 else 154,caption='附注37预收款项：不适用',unit='元',verification='附注明确不适用，非缺失补零')
records[2025]['values']['long_term_debt']=0.0
records[2024]['values']['long_term_debt']=33200000.0
records[2023]['values']['long_term_debt']=70270400.0
for y in records:
    records[y]['provenance']['long_term_debt']=dict(url=records[y]['source'],page=160 if y>=2024 else 78,caption='长期借款（不含一年内到期部分）',unit='元',verification='2025年附注45核对，其余合并资产负债表原值')
for y,value,page in ((2025,11610946.82,154),(2024,8392658.79,154),(2023,17923646.74,152)):
    pages=pages25 if y>=2024 else pages24
    assert f'{value:,.2f}' in pages[page-1]
    records[y]['values']['restricted_cash']=value
    records[y]['provenance']['restricted_cash']=dict(url=records[y]['source'],page=page,caption='附注31受限货币资金',unit='元',verification='官方年报原文核对')

meta=dict(company_name='佛山市海天调味食品股份有限公司',industry='食品制造业（调味品）',region='广东佛山',security_code='603288',listing_market='SH',listing_status='A股',input_contract='annual-v3',public_source='真实算例：海天味业2023—2025年公开合并财报（逐项核对）')
from finbridge.financial_history import flatten_history
from finbridge.data_contract import completeness
from finbridge.deep_diagnostics import historical_issues
data=flatten_history(meta,list(records.values()))
assert completeness(data)['complete']
assert not historical_issues(data),historical_issues(data)
case=dict(data=data,profile=dict(requested_amount=300000000.,requested_months=36,requested_purpose='设备购置',decision_engine='enterprise-v3',enterprise_type='一般企业',objective='测试假设：为设备更新安排3亿元外部净融资，期限36个月。评估是否有必要新增借款，并比较抵押贷款与设备租赁的成本、偿付压力及现金安全边界。'),
    title='海天味业 · 三年真实财报',description='2023—2025年合并财报；设备更新净融资3亿元、36个月（需求为测试假设）',
    notes=['2024、2025年取自2025年年报；2023年取自2024年年报比较列。2024年比较数据因同一控制下合并重述，2023年未据此自行追溯重编，跨该边界的变化包含口径影响。','金额均为人民币元；净利润为合并净利润，非归母净利润；货币资金与现金及现金等价物余额分别保留。','融资需求、未来利率、费用及资产融资比例属于演示假设；企业现金充足，不能据演示需求认定其缺钱或必须借款。'],
    sources=[dict(year=2025,url=URL25,sha256=hashlib.sha256((ROOT/'tmp/haitian2025/海天味业2025年年度报告.pdf').read_bytes()).hexdigest()),dict(year=2024,url=URL24,sha256=hashlib.sha256((ROOT/'tmp/haitian2024/annual.pdf').read_bytes()).hexdigest())])
(ROOT/'data/real_case_haitian.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf8')
rows=[['类别','科目','2023年度','2024年度','2025年度']]+[['企业信息',label,meta[key],'',''] for label,key in [('企业名称','company_name'),('所属行业','industry'),('所在地区','region')]]+[['企业信息','金额单位','元','','']]
for block,defs in BLOCKS.items():
    for key,label,_,_ in defs:rows.append([block,label,*[records[y]['values'][key] for y in records]])
(ROOT/'tmp/real-case-rows.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf8')
print(json.dumps(dict(years=list(records),required_per_year=len(REQUIRED),values_per_year=[len(r['values']) for r in records.values()],issues=historical_issues(data)),ensure_ascii=True))
