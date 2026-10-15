"""Transcribe official consolidated statements; never execute financing models."""
from pathlib import Path
import json,re,sys
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from finbridge.public_data import BLOCKS
from finbridge.data_contract import REQUIRED
BASE=ROOT/'tmp/official-cases'
CONFIG={
 'kingsoft':dict(name='北京金山办公软件股份有限公司',code='688111',industry='软件和信息技术服务业（办公软件）',region='北京海淀',role='demo',ranges={2025:((105,107),(109,110),(113,114)),2024:((126,128),(130,131),(134,135))}),
 'ninghu':dict(name='江苏宁沪高速公路股份有限公司',code='600377',industry='交通运输业（收费公路）',region='江苏南京',role='demo',ranges={2025:((144,146),(150,150),(154,155)),2024:((150,152),(156,156),(160,161))}),
 'fuyao':dict(name='福耀玻璃工业集团股份有限公司',code='600660',industry='汽车零部件制造业（汽车玻璃）',region='福建福清',role='test-only',ranges={2025:((80,82),(84,85),(87,88)),2024:((89,91),(93,94),(96,97))}),
 'ctg':dict(name='中国旅游集团中免股份有限公司',code='601888',industry='零售业（旅游免税零售）',region='北京东城',role='test-only',ranges={2025:((70,72),(74,75),(77,78)),2024:((70,72),(74,75),(77,78))}),
}
ALIASES={
 'ending_equity':['所有者权益（或股东权益）合计','股东权益合计'],
 'net_profit':['五、净利润','四、净利润'],
 'operating_profit':['三、营业利润','二、营业利润'],
 'revenue':['其中：营业收入','一、营业收入'],
 'cost_of_goods_sold':['其中：营业成本','减：营业成本'],
 'income_tax_expense':['减：所得税费用'],
 'cash_equivalents_balance':['六、期末现金及现金等价物余额','六、年末现金及现金等价物余额'],
 'opening_cash_equivalents':['加：期初现金及现金等价物余额','加：年初现金及现金等价物余额'],
 'net_investing_cash_flow':['投资活动产生的现金流量净额','投资活动使用的现金流量净额'],
 'net_financing_cash_flow':['筹资活动产生的现金流量净额','筹资活动(使用)/产生的现金流量净额','筹资活动产生/(使用)的现金流量净额'],
 'cash_effect_fx':['四、汇率变动对现金及现金等价物的影响'],
 'interest_expense':['其中：利息费用'],
}
MONEY=r'\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+\.\d{2}\)?'
def pattern(label):return r'\s*'.join(re.escape(c) for c in label)
def pair(pages,start,end,key,label):
 aliases=ALIASES.get(key,[label]);found=None
 for page in range(start,end+1):
  text=pages[page-1]
  for stop in ('母公司资产负债表','母公司利润表','母公司现金流量表'):
   if stop in text:text=text.split(stop)[0]
  for alias in aliases:
   match=re.search(r'(?m)^\s*'+pattern(alias),text)
   if not match:continue
   suffix=text[match.end():]
   # Captions may wrap; the amount line may be the following line.
   if key in ('net_profit','operating_profit') and suffix.lstrip().startswith(('（','(')):
    endparen=max(suffix.find('）'),suffix.find(')'))
    if endparen>=0:suffix=suffix[endparen+1:]
   lines=suffix.splitlines();line=lines[0]
   while len(re.findall(MONEY,line))<2 and len(lines)>1 and re.match(r'^\s*(?:[-(\d]|[一二三四五六七八九十]+[、（]\s*\d)',lines[1]):line+=' '+lines.pop(1)
   values=re.findall(MONEY,line)
   values=[float(Decimal(v.replace(',','').replace('(','-').replace(')',''))) for v in values]
   found=dict(values=values[:2],page=page,caption=alias,raw=line.strip())
   if len(values)>=2:return found
 return found or dict(values=[],page=None,caption=aliases[0],raw='未匹配')

def extract():
 reports=json.loads((BASE/'sources.json').read_text(encoding='utf8'));lookup={r['name']:r for r in reports}
 all_data={}
 for slug,cfg in CONFIG.items():
  extracted={}
  for year,ranges in cfg['ranges'].items():
   ps=json.loads((BASE/f'{slug}-{year}.json').read_text(encoding='utf8'));out={}
   for i,(block,defs) in enumerate(BLOCKS.items()):
    for key,label,_,_ in defs:
     if key not in REQUIRED and key!='interest_expense':continue
     idx=i if i<3 else 1
     out[key]=pair(ps,*ranges[idx],key,label)
   extracted[year]=out
  all_data[slug]=dict(config=cfg,extracted=extracted,sources=[lookup[f'{slug}-{y}'] for y in (2025,2024)])
 (BASE/'extracted.json').write_text(json.dumps(all_data,ensure_ascii=False,indent=2),encoding='utf8')
 for slug,c in all_data.items():
  for y,rows in c['extracted'].items():
   missing={k:v for k,v in rows.items() if len(v['values'])!=2}
   print(slug,y,json.dumps(missing,ensure_ascii=False))
 return all_data

def finalise(all_data):
 from finbridge.financial_history import flatten_history
 from finbridge.data_contract import completeness
 from finbridge.deep_diagnostics import historical_issues
 notes_zero={('kingsoft',2025,'short_term_debt'):193,('kingsoft',2024,'short_term_debt'):223,('kingsoft',2025,'long_term_debt'):198,('kingsoft',2024,'long_term_debt'):228,('kingsoft',2025,'advance_receipts'):194,('kingsoft',2024,'advance_receipts'):224,('fuyao',2025,'advance_receipts'):143,('fuyao',2024,'advance_receipts'):153}
 output=ROOT/'data/official_cases';output.mkdir(exist_ok=True)
 for slug,c in all_data.items():
  cfg=c['config'];sources={int(s['name'].split('-')[-1]):s for s in c['sources']}
  for year,rows in c['extracted'].items():
   ps=json.loads((BASE/f'{slug}-{year}.json').read_text(encoding='utf8'))
   for key,row in rows.items():
    if len(row['values'])==2:continue
    if (slug,year,key) in notes_zero:
     page=notes_zero[(slug,year,key)];caption=row['caption'];text=ps[page-1];pos=text.index(caption)
     assert '□适用' in text[pos:pos+150] and '√不适用' in text[pos:pos+150]
     row.update(values=[0.,0.],verification='合并表空栏；附注明确不适用，非缺失补零',note_page=page)
    elif slug=='kingsoft' and key=='historical_debt_repayment':
     # The full consolidated outflow subtotal equals the only two disclosed outflows.
     page=114 if year==2025 else 135;text=ps[page-1]
     totals=pair(ps,page,page,'subtotal','筹资活动现金流出小计')['values']
     dividends=pair(ps,page,page,'dividends','分配股利、利润或偿付利息支付的现金')['values']
     other=pair(ps,page,page,'other','支付其他与筹资活动有关的现金')['values']
     assert len(totals)==len(dividends)==len(other)==2
     assert all(abs(a-b-c)<.02 for a,b,c in zip(totals,dividends,other))
     assert re.search(pattern('偿还债务支付的现金')+r'\s*\n',text)
     row.update(values=[0.,0.],verification='合并表该行空栏；筹资流出小计与其余全部已列支出精确一致，核对零发生额',note_page=page)
    elif slug=='ninghu' and key=='cash_effect_fx':
     assert row['raw'].strip().startswith('- -')
     row.update(values=[0.,0.],verification='合并现金流量表两列均明确列示横线（零）')
    elif slug=='ninghu' and key=='research_expense':
     if year==2025:
      assert row['raw'].strip().endswith('-');row['values']=[91823.92,0.]
      row['verification']='2025年合并利润表原值；2024年比较列明确横线（零）'
     else:
      assert '研发投入' in ps[23] and '□适用' in ps[23] and '√不适用' in ps[23]
      row.update(values=[0.,0.],page=156,note_page=24,verification='合并利润表未列该费用项目；研发投入章节明确不适用；按报表单列研发费用零值保留，不解释为所有技术支出为零')
    else:raise AssertionError((slug,year,key,row))
  records=[]
  for y,report,col in [(2023,2024,1),(2024,2025,1),(2025,2025,0)]:
   values={k:r['values'][col] for k,r in c['extracted'][report].items()}
   provenance={k:dict(url=sources[report]['url'],page=r['page'],caption=r['caption'],unit='元',column='本期' if col==0 else '比较期',verification=r.get('verification','官方合并财报原值'),**({'note_page':r['note_page']} if r.get('note_page') else {})) for k,r in c['extracted'][report].items()}
   records.append(dict(year=y,values=values,provenance=provenance,source=sources[report]['url']))
  meta=dict(company_name=cfg['name'],industry=cfg['industry'],region=cfg['region'],security_code=cfg['code'],listing_market='SH',listing_status='A股',input_contract='annual-v3',public_source=f'官方年报逐项核对：{cfg["name"]}2023—2025年合并财报')
  data=flatten_history(meta,records)
  assert completeness(data)['complete'],completeness(data)
  assert not historical_issues(data),historical_issues(data)
  changes={k:(c['extracted'][2024][k]['values'][0],c['extracted'][2025][k]['values'][1]) for k in REQUIRED if c['extracted'][2024][k]['values'][0]!=c['extracted'][2025][k]['values'][1]}
  case=dict(data=data,role=cfg['role'],title=cfg['name']+' · 三年真实财报',description='2023—2025年官方合并财报；融资需求另列为演示假设',notes=['2025、2024取自2025年年报本期及比较列；2023取自2024年年报比较列。','原始数据保留人民币元；页面和Excel以亿元展示，净利润使用合并净利润，不使用归母净利润。','附注未取到的可选数据留空，不填造假数值。']+(['2024年比较数变化：'+json.dumps(changes,ensure_ascii=False)] if changes else ['两份年报重叠2024年核心字段核对一致。']),sources=[dict(year=y,**{k:sources[y][k] for k in ('url','sha256')}) for y in (2025,2024)])
  (output/(slug+'.json')).write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf8')
  print('VERIFIED',slug,len(REQUIRED),len(records),'restated_fields',len(changes))
if __name__=='__main__':finalise(extract())
