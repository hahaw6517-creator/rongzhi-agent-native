"""Readable public statement workbook assets and vertical CSV interchange."""
from pathlib import Path
import csv
from io import StringIO
from finbridge.public_data import BLOCKS,META,public_example


def annual_template_rows(example=False):
    """Latest first, with years explicitly supplied by the uploader."""
    if example:
        from finbridge.real_case import real_case_rows
        old=real_case_rows()
    else:old=history_template_rows(False)
    rows=[['类别','科目','最新年度','上一年度','上两年度'],['企业信息','年份',*([2025,2024,2023] if example else ['','',''])]]
    rows.extend([[r[0],r[1],*reversed(r[2:5])] if r[0]!='企业信息' else list(r) for r in old[1:]])
    return rows


def annual_template_csv(example=False):
    result=StringIO(newline='');csv.writer(result).writerows(annual_template_rows(example))
    return result.getvalue().encode('utf-8-sig')


def annual_template_xlsx(example=False):
    return (Path(__file__).resolve().parents[2]/'data'/('一年周转融资真实算例.xlsx' if example else '一年周转融资财报模板.xlsx')).read_bytes()


def public_template_xlsx(example=False):
    name="公开财务报表示例.xlsx" if example else "公开财务报表模板.xlsx"
    return (Path(__file__).resolve().parents[2]/"data"/name).read_bytes()


def history_template_rows(example=False,end_year=None):
    """Plain statement inputs, three comparable annual columns; no derived data."""
    data=public_example()
    data.update(operating_cash_flow=2800000,selling_expense=300000,administrative_expense=400000,research_expense=250000,finance_expense=180000,taxes_surcharges=100000,net_investing_cash_flow=-500000,net_financing_cash_flow=-800000,cash_effect_fx=0,opening_cash_equivalents=810000)
    from finbridge.data_contract import rolling_years,REQUIRED,SUPPLEMENTARY
    years=rolling_years(end_year)
    data['fixed_assets']=6500000
    rows=[['类别','科目',*[str(y)+'年度' for y in years]]]
    for label,value in [('企业名称','华辰制造（三年虚构模拟）' if example else '请填写企业名称'),('所属行业','制造业' if example else ''),('所在地区','江苏苏州' if example else ''),('金额单位','亿元')]:rows.append(['企业信息',label,value,'',''])
    ordered=[(block,definition) for block,defs in BLOCKS.items() for definition in defs if definition[0] in REQUIRED]+[('公开附注（可选）',definition) for defs in BLOCKS.values() for definition in defs if definition[0] in SUPPLEMENTARY]
    for block,definition in ordered:
        defs=[definition]
        for key,label,_,_ in defs:
            values=[]
            for index,scale in enumerate((.8,.9,1.)):
                value=data.get(key)
                if example and key=='net_profit':value=(500000,620000,768000)[index];scale=1
                elif example and key=='cost_of_goods_sold':value=(5600000,6200000,6720000)[index];scale=1
                elif example and key=='accounts_receivable':value=(1760000,2100000,2200000)[index];scale=1
                if example and key=='opening_cash_equivalents':value=(600000,720000,810000)[index];scale=1
                elif example and key=='net_financing_cash_flow':value=900000*scale-(600000,720000,810000)[index]-data['operating_cash_flow']*scale-data['net_investing_cash_flow']*scale;scale=1
                values.append(value*scale/1e8 if example and value is not None else '')
            rows.append([block,label,*values])
    return rows


def history_template_xlsx(example=False,end_year=None):
    """The same artifact-tool generator serves current and future annual headers."""
    from finbridge.data_contract import rolling_years
    from functools import lru_cache
    return _year_workbook(bool(example),rolling_years(end_year)[-1])


from functools import lru_cache
@lru_cache(maxsize=16)
def _year_workbook(example,end_year):
    import json,os,shutil,subprocess,tempfile
    root=Path(__file__).resolve().parents[2]
    asset=root/'data'/('三年财报示例.xlsx' if example else '三年财报模板.xlsx')
    manifest=root/'data/history-template-years.json'
    if asset.exists() and manifest.exists() and json.loads(manifest.read_text(encoding='utf8')).get('end_year')==end_year:return asset.read_bytes()
    node=os.getenv('FINBRIDGE_NODE') or shutil.which('node')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if not node and bundled.is_file():node=str(bundled)
    if not node:raise ValueError('动态Excel生成器不可用，请下载同年度CSV模板')
    with tempfile.TemporaryDirectory(prefix='finbridge-template-') as folder:
        spec=Path(folder)/'input.json';output=Path(folder)/'template.xlsx'
        spec.write_text(json.dumps(history_template_rows(example,end_year),ensure_ascii=False),encoding='utf8')
        result=subprocess.run([node,str(root/'scripts/history_workbook.mjs'),str(spec),str(output)],cwd=root,capture_output=True,timeout=35)
        if result.returncode or not output.is_file():raise ValueError('动态Excel生成失败，请使用CSV模板')
        return output.read_bytes()


def history_template_csv(example=False,end_year=None):
    result=StringIO(newline='');csv.writer(result).writerows(history_template_rows(example,end_year))
    return result.getvalue().encode('utf-8-sig')


def public_template_csv(example=False):
    data={**public_example(),"company_name":"华辰制造（虚构模拟）","operating_cash_flow":2800000,"prior_operating_cash_flow":2400000} if example else {"company_name":"请填写企业名称"}
    result=StringIO(newline="");writer=csv.writer(result)
    writer.writerow(["类别","科目","数值"])
    for label,key in META.items():writer.writerow(["企业信息",label,data.get(key,"")])
    writer.writerow(["企业信息","金额单位","元"])
    from finbridge.public_finance import NEEDED
    for block,rows in BLOCKS.items():
        for key,label,prior,_ in rows:
            writer.writerow([block if key in NEEDED else block+"（可选）",label,data.get(key,"")])
            if prior:writer.writerow([block+"（上期，可选）","上期"+label,data.get(prior,"")])
    return result.getvalue().encode("utf-8-sig")
