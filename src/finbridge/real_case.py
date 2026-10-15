"""Versioned, sourced example. Financial actuals and funding assumptions stay apart."""
from copy import deepcopy
import csv
from functools import lru_cache
from io import StringIO
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

@lru_cache(maxsize=1)
def _case():
    return json.loads((ROOT/'data/real_case_haitian.json').read_text(encoding='utf8'))

def real_case():
    c=deepcopy(_case())
    from finbridge.working_capital_year import year_profile
    c['profile']=year_profile({**c['profile'],'requested_amount':300000000.,'objective':'测试假设：下一年度生产经营周转净融资3亿元。固定12个月，检验需求必要性、误差校正现金和偿债边界。企业现金充足，测试需求不代表实际资金缺口。'})
    c['description']='三年真实合并财报；下一年度生产经营周转净融资3亿元、12个月（测试假设）'
    c['notes']=[n for n in c['notes'] if '融资需求' not in n]+['融资需求为一年期生产经营周转测试，非公司实际融资计划；现金充足时应优先评估自有资金，不因填报需求就认定必须借款。']
    return c

def real_cases():
    from finbridge.working_capital_year import year_profile
    cases=[real_case()]
    for slug in ('kingsoft','ninghu'):
        path=ROOT/'data/official_cases'/f'{slug}.json'
        if not path.exists():continue
        c=json.loads(path.read_text(encoding='utf8'))
        c['profile']=year_profile(dict(requested_amount=300000000.,objective='对照演示：下一年度生产经营周转净融资3亿元，12个月。金额为统一演示假设，不代表企业真实融资计划。'))
        c['description']='2023—2025年官方合并财报；统一3亿元净需求、12个月生产经营周转（演示假设）'
        record_path=ROOT/'data/official_cases/demo_verification.json'
        if record_path.exists():c['description']+='。'+json.loads(record_path.read_text(encoding='utf8')).get(slug,'')
        c['notes'].append('与海天算例使用相同净融资金额、利率、费用和安全规则；不调整财报以制造渠道差异。')
        if slug=='ninghu':c['notes'].append('本例用于展示模型边界：年度现金均匀分配、营业成本代理储备及历史结构压力可能较保守；未通过不等于企业实际月度现金不足或银行拒贷。')
        cases.append(c)
    return cases

def find_real_case(data):
    return next((c for c in real_cases() if all(data.get(k)==c['data'].get(k) for k in ('company_name','public_source'))),None)

def is_real_case(data):
    return find_real_case(data) is not None

def case_context(data):
    case=find_real_case(data)
    if case is None:return None
    return {k:case[k] for k in ('title','description','notes','sources')}

def real_case_rows():
    from finbridge.public_data import BLOCKS
    d=_case()['data'];history=d['financial_history']
    rows=[['类别','科目',*[str(r['year'])+'年度' for r in history]]]
    rows += [['企业信息',label,d[key],'',''] for label,key in [('企业名称','company_name'),('所属行业','industry'),('所在地区','region')]]
    rows.append(['企业信息','金额单位','亿元','',''])
    for block,defs in BLOCKS.items():
        for key,label,_,_ in defs:rows.append([block,label,*[r['values'][key]/1e8 if r['values'].get(key) is not None else '' for r in history]])
    return rows

def real_case_csv():
    text=StringIO(newline='');csv.writer(text).writerows(real_case_rows())
    return text.getvalue().encode('utf-8-sig')
