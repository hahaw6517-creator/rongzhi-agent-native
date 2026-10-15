"""Validated annual observations; presentation columns never become invented history."""
from copy import deepcopy
import math
import re
from numbers import Real

def validate_history(records):
    from finbridge.public_data import BLOCKS
    fields={k for rows in BLOCKS.values() for k,_,_,_ in rows}
    signed={k for rows in BLOCKS.values() for k,_,_,s in rows if s}
    if not isinstance(records,list) or len(records)>5:raise ValueError('历史财报须为最多五个年度')
    result=[];seen=set()
    for row in records:
        if not isinstance(row,dict) or set(row)-{'year','values','source','provenance'}:raise ValueError('历史财报结构无效')
        year=row.get('year');values=row.get('values')
        if isinstance(year,bool) or not isinstance(year,int) or not 1900<=year<=2100 or year in seen:raise ValueError('历史年度重复或无效')
        if not isinstance(values,dict) or set(values)-fields:raise ValueError('历史科目不在财报模板中')
        for k,v in values.items():
            if v is not None and (isinstance(v,bool) or not isinstance(v,Real) or not math.isfinite(v) or abs(v)>1e15 or v<0 and k not in signed):raise ValueError('历史财务数值无效：'+k)
        if not isinstance(row.get('source',''),str) or len(row.get('source',''))>1500:raise ValueError('年度来源格式无效')
        if not isinstance(row.get('provenance',{}),dict):raise ValueError('年度来源位置无效')
        seen.add(year);result.append(deepcopy(row))
    return sorted(result,key=lambda r:r['year'])

def annual_records(raw):
    from finbridge.public_data import BLOCKS
    if raw.get('financial_history'):
        rows=validate_history(raw['financial_history'])
        latest=rows[-1] if rows else None
        if latest:
            period=re.fullmatch(r'(20\d{2})(?:年度|年|-12-31)?',str(raw.get('report_period','')))
            if not period or int(period.group(1))!=latest['year']:raise ValueError('报告期须与最近历史年度一致')
            # Explicit latest-year corrections and temporary assumptions own this version.
            latest['values'].update({k:raw[k] for defs in BLOCKS.values() for k,_,_,_ in defs if k in raw})
        return rows
    year=re.search(r'20\d{2}',str(raw.get('report_period','')))
    if not year:return []
    current={k:raw.get(k) for rows in BLOCKS.values() for k,_,_,_ in rows}
    previous={k:raw[prior] for rows in BLOCKS.values() for k,_,prior,_ in rows if prior and raw.get(prior) is not None}
    rows=[dict(year=int(year.group()),values=current,source=raw.get('public_source','用户财报'))]
    if previous:rows.insert(0,dict(year=int(year.group())-1,values=previous,source='旧模板提供的上期科目，不视为完整上期报表'))
    return rows

def flatten_history(meta,records):
    from finbridge.public_data import BLOCKS,SCHEMA
    rows=validate_history(records)
    if not rows:raise ValueError('至少需要一个有数值的年度')
    latest=rows[-1];result={**meta,**latest['values'],'statement_schema':SCHEMA,'report_period':str(latest['year'])+'年度','financial_history':rows}
    result['public_provenance']=deepcopy(latest.get('provenance',{}))
    previous=next((r for r in rows if r['year']==latest['year']-1),None)
    for defs in BLOCKS.values():
        for k,_,prior,_ in defs:
            if prior:result[prior]=previous['values'].get(k) if previous else None
    return result

def parse_history_sheet(sheets):
    import pandas as pd
    from finbridge.public_data import BLOCKS,META
    captions={label:(key,signed) for defs in BLOCKS.values() for key,label,_,signed in defs}
    for sheet,frame in sheets.items():
        rows=frame.fillna('').values.tolist()
        if not rows or list(rows[0][:2])!=['类别','科目'] or len(rows[0])<4:continue
        columns=[]
        relative=list(rows[0][2:5])==['最新年度','上一年度','上两年度']
        if relative:
            year_rows=[row for row in rows[1:] if len(row)>1 and str(row[1]).strip()=='年份']
            if len(year_rows)!=1:raise ValueError('请在年份一行填写三个完整年度，例如2025、2024、2023')
            from finbridge.data_contract import china_today
            for i in range(2,5):
                try:
                    text=str(year_rows[0][i]).strip().removesuffix('.0');year=int(text)
                except (ValueError,IndexError):raise ValueError('请完整填写最新年度、上一年度、上两年度的年份') from None
                if not 2002<=year<china_today().year:raise ValueError('年份应为已结束的完整年度，不能使用当前年或未来年')
                columns.append((i,year))
            if [y for _,y in columns]!=list(range(columns[0][1],columns[0][1]-3,-1)):raise ValueError('三列年份应从最新到最早连续递减，例如2025、2024、2023')
        for i,h in enumerate(rows[0][2:],2):
            m=re.fullmatch(r'(20\d{2})(?:年度|年)?',str(h).strip().removesuffix('.0'))
            if m:columns.append((i,int(m.group(1))))
        if not columns:continue
        if len({y for _,y in columns})!=len(columns):raise ValueError('年度列重复')
        meta={};unit='元';seen=set()
        for row in rows[1:]:
            if len(row)<3:continue
            label=str(row[1]).strip()
            if label in META:meta[META[label]]=str(row[2]).strip()
            if label=='金额单位':unit=str(row[2]).strip() or '元'
        if not meta.get('company_name') or meta['company_name']=='请填写企业名称':raise ValueError('请填写企业名称')
        if unit not in {'元','万元','亿元'}:raise ValueError('金额单位须为元、万元或亿元')
        scale={'元':1,'万元':1e4,'亿元':1e8}[unit]
        records={y:dict(year=y,values={},source=meta.get('public_source','用户上传财报'),provenance={}) for _,y in columns}
        for n,row in enumerate(rows[1:],2):
            if len(row)<2:continue
            label=str(row[1]).strip()
            if label in META or label in {'金额单位','年份'} or not label:continue
            if label not in captions:
                if any(i<len(row) and row[i]!='' for i,_ in columns):raise ValueError('无法识别财报科目：'+label)
                continue
            key,signed=captions[label]
            if key in seen:raise ValueError('科目重复：'+label)
            seen.add(key)
            for i,y in columns:
                value=row[i] if i<len(row) else ''
                if value in ('','—','-','未披露'):continue
                text=str(value).strip().replace(',','').replace('，','')
                try:v=float('-'+text[1:-1] if text.startswith('(') and text.endswith(')') else text)*scale
                except (ValueError,TypeError):raise ValueError(label+'须直接填写金额') from None
                if isinstance(value,bool) or not math.isfinite(v) or abs(v)>1e15 or v<0 and not signed:raise ValueError(label+'金额无效')
                records[y]['values'][key]=round(v,2) if scale>1 else v
                records[y]['provenance'][key]=dict(sheet=sheet,cell=chr(65+i)+str(n),unit=unit,public_reference=records[y]['source'])
        from finbridge.data_contract import CONTRACT
        # Preserve empty annual columns so completeness can name the missing year.
        return pd.DataFrame([flatten_history(dict(meta,input_contract=CONTRACT),list(records.values()))])
    return None
