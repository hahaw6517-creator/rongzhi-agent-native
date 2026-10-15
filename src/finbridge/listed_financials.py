"""A-share public annual statements. Retrieval is a reviewable draft, not certification."""
from concurrent.futures import ThreadPoolExecutor
from finbridge.data_contract import china_today,rolling_years,REQUIRED,CONTRACT,completeness
import re
import httpx
from finbridge.financial_history import flatten_history

MAPS={
 'GBALANCE':dict(total_assets='TOTAL_ASSETS',total_liabilities='TOTAL_LIABILITIES',current_assets='TOTAL_CURRENT_ASSETS',current_liabilities='TOTAL_CURRENT_LIAB',ending_equity='TOTAL_EQUITY',cash_and_equivalents='MONETARYFUNDS',accounts_receivable='ACCOUNTS_RECE',inventory='INVENTORY',accounts_payable='ACCOUNTS_PAYABLE',prepayments='PREPAYMENT',advance_receipts='ADVANCE_RECEIVABLES',contract_liabilities='CONTRACT_LIAB',short_term_debt='SHORT_LOAN',long_term_debt='LONG_LOAN',current_portion_long_term_debt='NONCURRENT_LIAB_1YEAR'),
 'GINCOME':dict(revenue='OPERATE_INCOME',cost_of_goods_sold='OPERATE_COST',net_profit='NETPROFIT',operating_profit='OPERATE_PROFIT',income_tax_expense='INCOME_TAX',selling_expense='SALE_EXPENSE',administrative_expense='MANAGE_EXPENSE',research_expense='RESEARCH_EXPENSE',finance_expense='FINANCE_EXPENSE',taxes_surcharges='OPERATE_TAX_ADD',interest_expense='FE_INTEREST_EXPENSE'),
 'GCASHFLOW':dict(operating_cash_flow='NETCASH_OPERATE',capital_expenditure='CONSTRUCT_LONG_ASSET',cash_equivalents_balance='END_CCE',historical_debt_repayment='PAY_DEBT_CASH',net_investing_cash_flow='NETCASH_INVEST',net_financing_cash_flow='NETCASH_FINANCE',cash_effect_fx='RATE_CHANGE_EFFECT',opening_cash_equivalents='BEGIN_CCE'),
}
MAPS['GBALANCE']['fixed_assets']='FIXED_ASSET'

def retrieve_a_share(code,market,industry='',region='',client=None,as_of=None):
    code=str(code).strip();market=str(market).upper()
    if not re.fullmatch(r'\d{6}',code) or market not in {'SH','SZ','BJ'}:raise ValueError('请填写六位A股代码并选择沪、深、北市场')
    today=as_of or china_today()
    own=client is None;client=client or httpx.Client(timeout=20,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'})
    try:
        reply=client.post('https://www.cninfo.com.cn/new/information/topSearch/query',data={'keyWord':code,'maxNum':10});reply.raise_for_status();identities=reply.json()
        matches=[x for x in identities if x.get('code')==code and x.get('category')=='A股']
        if len(matches)!=1:raise ValueError('未能唯一确认A股证券身份，请检查代码和市场')
        identity=matches[0];kind=str(identity.get('type','')).lower()
        if market=='SH' and 'sh' not in kind or market=='SZ' and 'sz' not in kind or market=='BJ' and not any(s in kind for s in ('bj','neeq')):raise ValueError('证券代码与所选市场不一致')
        def fetch(kind):
            url='https://datacenter.eastmoney.com/securities/api/data/v1/get'
            r=client.get(url,params=dict(reportName='RPT_F10_FINANCE_'+kind,filter=f'(SECUCODE="{code}.{market}")',columns='ALL',pageNumber=1,pageSize=24,sortTypes=-1,sortColumns='REPORT_DATE',source='HSF10',client='PC'));r.raise_for_status()
            body=r.json();rows=(body.get('result') or {}).get('data',[])
            if not isinstance(rows,list):raise ValueError('财报数据源返回结构异常')
            annual={}
            for v in rows:
                stamp=str(v.get('REPORT_DATE',''))[:10]
                notice=str(v.get('NOTICE_DATE') or '')[:10]
                if re.fullmatch(r'20\d{2}-12-31',stamp) and int(stamp[:4])<today.year and re.fullmatch(r'20\d{2}-\d{2}-\d{2}',notice) and notice<=today.isoformat() and str(v.get('CURRENCY','')).upper() in {'CNY','人民币','RMB'}:
                    year=int(stamp[:4]);annual.setdefault(year,v)
            return kind,annual
        with ThreadPoolExecutor(max_workers=3) as pool:tables=dict(pool.map(fetch,MAPS))
        available=set.union(*(set(x) for x in tables.values()))
        if not available:raise ValueError('没有检索到已披露人民币年度财报，请下载三年模板上传')
        years=rolling_years(max(available),today)
        records=[]
        for year in years:
            values={};provenance={}
            for kind,mapping in MAPS.items():
                row=tables[kind].get(year,{})
                for key,field in mapping.items():
                    value=row.get(field)
                    if value is None:continue
                    if isinstance(value,bool) or not isinstance(value,(int,float)):continue
                    values[key]=value;provenance[key]=dict(provider='东方财富结构化财报',report=kind,field=field,year=year,unit='元',notice_date=row.get('NOTICE_DATE'),verification='待与官方合并年报逐项核对')
            records.append(dict(year=year,values=values,provenance=provenance,source='东方财富结构化财报；官方年报入口见检索结果'))
        links=[];warning=''
        try:
            r=client.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',data=dict(pageNum=1,pageSize=100,column={'SH':'sse','SZ':'szse','BJ':'bse'}[market],tabName='fulltext',stock=code+','+identity['orgId'],searchkey='年度报告',seDate=f'{min(years)+1}-01-01~{today.isoformat()}',isHLtitle='false'));r.raise_for_status()
            for x in r.json().get('announcements',[]) or []:
                title=re.sub('<[^>]+>','',x.get('announcementTitle',''));path=x.get('adjunctUrl','');m=re.search(r'(20\d{2})年?年度报告',title)
                if m and int(m.group(1)) in years and not any(s in title for s in ('摘要','英文','取消','H股')) and re.fullmatch(r'finalpage/[\w./-]+\.PDF',path,re.I):links.append(dict(year=int(m.group(1)),title=title,url='https://static.cninfo.com.cn/'+path))
        except (httpx.HTTPError,ValueError,KeyError):warning='官方年报链接暂未获取，请自行核对年报原文。'
        meta=dict(company_name=identity.get('zwjc',code),security_code=code,listing_market=market,listing_status='A股',industry=industry or '未披露',region=region or '未披露',public_source='东方财富公开结构化财报（待复核）',input_contract=CONTRACT)
        data=flatten_history(meta,records)
        missing={str(r['year']):[k for k in REQUIRED if r['values'].get(k) is None] for r in records}
        quality=completeness(data)
        from finbridge.deep_diagnostics import historical_issues
        issues=historical_issues(data)
        return dict(records=[data],quality=[quality],filename=f'{code}公开年度财报',retrieval=dict(as_of=today.isoformat(),years=years,latest_available_year=max(available),template_required=not quality['complete'] or bool(issues),annual_basis='截至查询日最新已披露年度及此前两个连续年度；尚未披露的新年度不强行取数。',official_reports=links,missing=missing,issues=issues,warning=quality['message'] if not quality['complete'] else warning or '必要科目已取齐，仍需与官方合并年报核对；结构化数据不代表审计认证。'))
    finally:
        if own:client.close()
