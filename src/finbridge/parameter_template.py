"""Fixed Chinese labels and units for reliable batch scenario adjustments."""
import math
import re
from finbridge.dialogue_edits import PARAMETERS
from finbridge.public_finance import LIMITS

HEADER='[参数调整]'
UNITS={'money':'亿元','percent':'%','days':'天','multiple':'倍','number':'数值'}

def definitions():
    return [dict(key=k,label=label,unit=UNITS[kind],kind=kind) for k,(label,kind) in PARAMETERS.items()]

def template_text():
    return HEADER+'\n'+'\n'.join(f"{x['label']}（{x['unit']}）=" for x in definitions())

def parse_template(text,run):
    defs={f"{x['label']}（{x['unit']}）":x for x in definitions()}
    if HEADER not in text and not any(label in text for label in defs):return None
    changes={};items=[]
    profile=run['input_profile'];assumptions=run['public_analysis']['assumptions']
    from finbridge.decision_chat import recommended_portfolio
    p=recommended_portfolio(run['outputs']);products={c['id']:c for c in p['composition']}
    defaults=dict(cvar_alpha=.8,cvar_weight=.1,calibration_share=.5,calibration_limit=.3,receivable_delay_days=p.get('annual_context',{}).get('delay_days',5),margin_drop=p.get('annual_context',{}).get('margin_drop',.01))
    for index,line in enumerate(text.splitlines(),1):
        line=line.strip().replace('(', '（').replace(')', '）').replace('＝','=')
        if not line or line==HEADER or line.startswith('#') or line in ('```','```text'):continue
        if '=' not in line:raise ValueError(f'第{index}行请使用“参数名（单位）=数值”，不要在模板里混入其他要求。')
        label,raw=line.split('=',1);label=label.strip();raw=raw.strip()
        if label not in defs:raise ValueError(f'第{index}行参数名称或单位不匹配，请从折叠区复制对应行。')
        x=defs[label];key=x['key']
        if not raw or raw in ('不变','保持不变','保持'):continue
        if key in changes:raise ValueError(f"{x['label']}填写了两次，请保留一个最终值。")
        raw=raw.replace(',','').replace('，','')
        if raw.endswith(x['unit']):raw=raw[:-len(x['unit'])].strip()
        if not re.fullmatch(r'[-+]?\d+(?:\.\d+)?',raw):raise ValueError(f"第{index}行请填写数值；单位已在参数名中标明，不要写增减指令。")
        display=float(raw);value=display*(1e8 if x['kind']=='money' else .01 if x['kind']=='percent' else 1)
        lo,hi=(.01,1e10) if key=='requested_amount' else LIMITS[key]
        scale=1e8 if x['kind']=='money' else .01 if x['kind']=='percent' else 1
        if not math.isfinite(value) or not lo<=value<=hi:raise ValueError(f"{x['label']}支持范围为{lo/scale:g}—{hi/scale:g}{x['unit']}，请修改后重新发送模板。")
        old=profile.get(key,assumptions.get(key,defaults.get(key)))
        for prefix,c in products.items():
            suffix=key.removeprefix(prefix+'_') if key.startswith(prefix+'_') else None
            if suffix in ('rate','fee_rate','fixed_fee','limit'):old=profile.get(key,c['capacity'] if suffix=='limit' else c[suffix])
        changes[key]=value;items.append(dict(key=key,label=x['label'],before=old,after=value,unit=x['kind']))
    if not changes:raise ValueError('模板还没有填写数值。请至少填写一项，要保持不变的行留空即可。')
    return dict(changes=changes,items=items)
