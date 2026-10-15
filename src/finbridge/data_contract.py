"""Shared financial input requirements for templates, retrieval and model gates."""
from datetime import datetime, timezone, timedelta
from finbridge.public_data import BLOCKS

CONTRACT='annual-v3'
# All selected captions on the three statements are required. Only notes remain optional.
SUPPLEMENTARY={'restricted_cash','interest_expense','depreciation_expense','amortization_expense'}
REQUIRED=tuple(k for block,defs in BLOCKS.items() for k,_,_,_ in defs if k not in SUPPLEMENTARY)
LABELS={k:label for defs in BLOCKS.values() for k,label,_,_ in defs}

def china_today():return datetime.now(timezone(timedelta(hours=8))).date()

def rolling_years(end_year=None,as_of=None):
    today=as_of or china_today();end=today.year-1 if end_year is None else int(end_year)
    if not 2002<=end<today.year:raise ValueError('年报截止年度须早于当前年份，且不早于2002年')
    return list(range(end-2,end+1))

def completeness(raw):
    from finbridge.financial_history import annual_records
    rows=annual_records(raw);missing=[];years=[r['year'] for r in rows]
    for key,label in [('company_name','企业名称'),('industry','所属行业'),('region','所在地区')]:
        if not str(raw.get(key) or '').strip() or raw.get(key)=='未披露':missing.append(dict(year='企业信息',key=key,label=label))
    expected=list(range(max(years)-2,max(years)+1)) if years else rolling_years()
    for year in expected:
        row=next((r for r in rows if r['year']==year),None);values=row['values'] if row else {}
        for key in REQUIRED:
            if values.get(key) is None:missing.append(dict(year=year,key=key,label=LABELS[key]))
    return dict(complete=not missing,required_per_year=len(REQUIRED),required_years=expected,available_years=years,missing=missing,template_required=bool(missing),message='必要数据齐全，可进入诊断与融资计算。' if not missing else f'缺少{len(missing)}个必要年度科目，请下载模板补齐后上传；未披露不自动视为零。')
