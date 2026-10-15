"""Typed natural-language edits: model extracts, server validates, Python computes."""
import math
import re
from finbridge.public_finance import LIMITS

PARAMETERS={
 'requested_amount':('净融资需求','money'),
 'assumed_rate':('统一参考年利率','percent'),
 'reserve_days':('现金储备天数','days'),
 'maintenance_share':('维持性投资比例','percent'),
 'max_leverage':('负债率上限','percent'),
 'target_coverage':('偿债覆盖安全线','multiple'),
 'cash_drop':('压力现金下降幅度','percent'),
 'rate_up':('压力加息幅度','percent'),
 'forecast_growth':('预测收入增长率','percent'),
 'credit_revenue_ratio':('信用额度收入折算比例','percent'),
 'secured_advance_ratio':('抵押资产融资比例','percent'),
 'factoring_advance_ratio':('应收账款融资比例','percent'),
 'cvar_alpha':('CVaR置信水平','percent'),
 'cvar_weight':('CVaR权重','number'),
 'calibration_share':('预测误差修正比例','percent'),
 'calibration_limit':('预测修正限幅比例','percent'),
 'receivable_delay_days':('压力回款延迟天数','days'),
 'margin_drop':('压力毛利率下降幅度','percent'),
}
for prefix,label in [('credit','信用贷款'),('secured','抵押贷款'),('factoring','应收账款质押贷款')]:
 for suffix,title,unit in [('rate','年利率','percent'),('fee_rate','手续费率','percent'),('fixed_fee','固定费用','money'),('limit','本金上限','money')]:
  PARAMETERS[prefix+'_'+suffix]=(label+title,unit)

class EditClarification(ValueError):
 def __init__(self,parameter,edits,message):
  super().__init__(message);self.parameter=parameter;self.edits=edits

def money_literals(text):
 """Read amounts from the user's text, never from model-converted figures."""
 from finbridge.decision_chat import chinese_number,NUM
 text=re.sub(r'(?<=\d)[,，](?=\d{3}(?:\D|$))','',text)
 return [dict(amount=chinese_number(m.group(1))*{'亿元':1e8,'亿':1e8,'万元':1e4,'万':1e4,'元':1}[m.group(2)],text=m.group()) for m in re.finditer('('+NUM+r')\s*(亿元|万元|亿|万|元)',text)]

def source_evidence(key,quote,question):
 """Recover exact field-labelled user text when the model rewrites its quote."""
 if isinstance(quote,str) and quote.strip() and quote in question:return quote
 patterns={'requested_amount':r'(?:净?融资需求|融资金额|需求金额|想借|想融)',
  'credit_limit':r'(?:信用贷款|信用贷).*(?:额度|上限|最多|不用|禁用)',
  'secured_limit':r'(?:抵押贷款|抵押贷).*(?:额度|上限|最多|不用|禁用)',
  'factoring_limit':r'(?:应收|质押).*(?:额度|上限|最多|不用|禁用)',
  'max_leverage':r'负债率|杠杆上限','target_coverage':r'偿债覆盖|安全线|DSCR',
  'reserve_days':r'储备|留存.*天','forecast_growth':r'收入.*增长|营收.*增长',
  'maintenance_share':r'维持性投资','cvar_alpha':r'CVaR.*置信|置信水平',
  'cvar_weight':r'CVaR.*权重|风险权重','calibration_share':r'误差.*(?:修正|转移)|修正比例',
  'calibration_limit':r'修正.*(?:上限|限幅)','cash_drop':r'现金.*下降',
  'rate_up':r'压力.*加息|加息幅度','receivable_delay_days':r'回款.*延迟|应收.*延迟',
  'margin_drop':r'毛利率.*下降','assumed_rate':r'(?:统一|参考).*利率'}
 for prefix,name in [('credit',r'信用(?:贷款|贷)?'),('secured',r'抵押(?:贷款|贷)?'),('factoring',r'(?:应收|质押)')]:
  patterns[prefix+'_rate']=name+r'.*(?:年?利率|报价)'
  patterns[prefix+'_fee_rate']=name+r'.*(?:手续费率|费率)'
  patterns[prefix+'_fixed_fee']=name+r'.*(?:固定费用|固定手续费)'
 patterns.update(credit_revenue_ratio=r'信用.*(?:收入|折算|比例)',secured_advance_ratio=r'抵押.*(?:资产.*比例|融资比例)',factoring_advance_ratio=r'应收.*(?:融资比例|折算比例)')
 pattern=patterns.get(key)
 clauses=re.split(r'[，,；;。\n]',question)
 matches=[c.strip() for c in clauses if pattern and re.search(pattern,c)]
 return matches[-1] if matches else None

def edit_schema():
 return dict(type='function',function=dict(name='explore_financing',description='用户自然表达修改融资需求或任意多个假设时，提取每项变更并调用Python生成临时方案；不改正式报告。增加1个百分点是add+percentage_points，不是set；增加10%是increase_percent+percent。缺单位、基准或歧义请先ask_clarification。禁止把财报原值放入本工具。',parameters=dict(type='object',properties=dict(
  edits=dict(type='array',minItems=1,maxItems=30,items=dict(type='object',properties=dict(parameter=dict(type='string',enum=list(PARAMETERS)),operation=dict(type='string',enum=['set','add','subtract','increase_percent','decrease_percent']),value=dict(type='number'),unit=dict(type='string',enum=['yuan','wan','yi','percent','percentage_points','days','multiple','number']),evidence=dict(type='string',description='当前用户消息或待澄清要求中的逐字原文，包含该项数值与单位')),required=['parameter','operation','value','unit','evidence'],additionalProperties=False)),base_scenario_id=dict(type='string',description='用户明确说基于刚才的临时方案时填写该ID，否则基于正式报告')),required=['edits'],additionalProperties=False)))

def resolve_edits(edits,run,question):
 from finbridge.decision_chat import chinese_number,NUM,recommended_portfolio
 if not isinstance(edits,list) or not 1<=len(edits)<=30:raise ValueError('请说清楚希望调整的参数及数值。')
 profile=run['input_profile'];model=run['public_analysis'];a=model['assumptions'];plan=recommended_portfolio(run['outputs'])
 products={c['id']:c for c in plan['composition']};changes={};items=[]
 defaults=dict(cvar_alpha=.8,cvar_weight=.1,calibration_share=.5,calibration_limit=.3)
 defaults.update(receivable_delay_days=plan.get('annual_context',{}).get('delay_days',5),margin_drop=plan.get('annual_context',{}).get('margin_drop',.01))
 for edit in edits:
  if not isinstance(edit,dict) or set(edit)!={'parameter','operation','value','unit','evidence'}:raise ValueError('请补充要调整的参数、变化方向和数值。')
  key,op,value,unit,quote=[edit[k] for k in ('parameter','operation','value','unit','evidence')]
  if key not in PARAMETERS:raise ValueError('该参数尚未开放。可以调整融资需求、产品报价额度、现金预测和压力假设。')
  label,kind=PARAMETERS[key]
  if key in changes:raise EditClarification(key,edits,f'{label}出现了不同设定，请确认最终采用哪个值。')
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise EditClarification(key,edits,f'请给出有效的{label}数值。')
  if op!='set' and value<0:raise EditClarification(key,edits,f'请用正数表示{label}的增减幅度，并说明方向。')
  quote=source_evidence(key,quote,question)
  if not quote:raise EditClarification(key,edits,f'请确认{label}的具体数值和单位。')
  compact=re.sub(r'[,，\s]','',quote)
  disabled=key.endswith('_limit') and op=='set' and value==0 and bool(re.search(r'不用|不使用|不考虑|禁用|关闭|排除',compact))
  nums=[chinese_number(m.group(2))*(-1 if m.group(1) else 1) for m in re.finditer('([-−负]?)('+NUM+')',compact)]
  if kind=='money' and not disabled and op not in ('increase_percent','decrease_percent'):
   literals=money_literals(quote)
   amounts=list(dict.fromkeys(x['amount'] for x in literals))
   if len(amounts)!=1:raise EditClarification(key,edits,f'请明确{label}最终采用的金额及单位。')
   # The user is the source of truth. 5亿元 and 50000万元 both become 5e8元,
   # even if the model sends already-converted value or a rewritten quotation.
   value=amounts[0];unit='yuan';compact=str(value)+'元';nums=[value]
  if kind=='percent' and op not in ('increase_percent','decrease_percent'):
   pct=list(re.finditer('([-−负]?)('+NUM+r')\s*(?:%|％|个百分点|个点)',compact))
   if len(pct)==1:
    value=chinese_number(pct[0].group(2))*(-1 if pct[0].group(1) else 1)
    nums=[value]
  if kind in ('multiple','days'):
   scalar=list(re.finditer('([-−负]?)('+NUM+r')\s*'+('倍' if kind=='multiple' else '天'),compact))
   if len(scalar)==1:
    value=chinese_number(scalar[0].group(2))*(-1 if scalar[0].group(1) else 1);nums=[value]
  if not disabled and not any(abs(value-v)<1e-8 for v in nums):raise EditClarification(key,edits,f'请说明{label}的新值和单位。')
  if disabled:amount=0
  elif op in ('increase_percent','decrease_percent'):
   if unit!='percent' or not re.search(r'%|％|百分之',compact):raise EditClarification(key,edits,f'请确认{label}的相对变化百分比。')
   amount=value/100
  elif kind=='money':
   units={'yuan':('元',1),'wan':('万',1e4),'yi':('亿',1e8)}
   supplied='yi' if '亿' in compact else 'wan' if '万' in compact else 'yuan' if '元' in compact else None
   if unit not in units or unit!=supplied:raise EditClarification(key,edits,f'{label}的金额单位是什么：元、万元还是亿元？')
   amount=value*units[unit][1]
  elif kind=='percent':
   if unit not in ('percent','percentage_points') or not re.search(r'%|％|百分之|百分点|个点',compact):raise EditClarification(key,edits,f'请说明{label}是设置为百分之几，还是增加/减少几个百分点。')
   if op in ('add','subtract') and unit!='percentage_points':raise EditClarification(key,edits,f'{label}变化{value}%是相对增减，还是增减{value}个百分点？')
   if unit=='percentage_points' and not re.search(r'百分点|个点',compact):raise EditClarification(key,edits,f'请确认{label}变化是否指百分点。')
   amount=value/100
  else:
   if unit!=kind:raise EditClarification(key,edits,f'请说明{label}的单位。')
   if kind=='days' and '天' not in compact:raise EditClarification(key,edits,f'请确认{label}是否以天为单位。')
   amount=value
  old=profile.get(key,a.get(key,defaults.get(key)))
  for prefix,product in products.items():
   suffix=key.removeprefix(prefix+'_') if key.startswith(prefix+'_') else None
   if suffix in ('rate','fee_rate','fixed_fee','limit'):old=profile.get(key,product['capacity'] if suffix=='limit' else product[suffix])
  if op=='set':new=amount
  elif old is None:raise EditClarification(key,edits,f'缺少{label}基准值，请直接指定新值。')
  elif op=='add':new=old+amount
  elif op=='subtract':new=old-amount
  elif op=='increase_percent':new=old*(1+amount)
  elif op=='decrease_percent':new=old*(1-amount)
  else:raise ValueError('请说明是设置新值、增加还是减少。')
  lo,hi=(.01,1e10) if key=='requested_amount' else LIMITS[key]
  if not math.isfinite(new) or not lo<=new<=hi:
   scale=100 if kind=='percent' else 1
   raise EditClarification(key,edits,f'{label}超出当前模型支持范围（{lo*scale:g}—{hi*scale:g}'+('%' if kind=='percent' else '元' if kind=='money' else '')+'），请给出范围内数值。')
  changes[key]=new;items.append(dict(key=key,label=label,before=old,after=new,unit=kind))
 return changes,items
