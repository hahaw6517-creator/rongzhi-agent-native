'use strict';
// Charts consume the same Python outputs as the report; no forecast or solver runs here.
const FIN_COLORS=['#147d68','#527fa7','#b17b31','#805aa0'];
function finFigure(title,body,caption){return `<figure class="fin-figure"><h3>${e(title)}</h3>${body}<figcaption>${e(caption)}</figcaption></figure>`;}
function finLegend(series){return `<div class="fin-legend">${series.map((s,i)=>`<span><i style="background:${s.color||FIN_COLORS[i%4]}"></i>${e(s.name)}</span>`).join('')}</div>`;}
function finColumns(labels,series,unit='亿元'){
 const vals=series.flatMap(s=>s.values).filter(v=>typeof v==='number'&&Number.isFinite(v));
 if(!vals.length)return '<p>暂无可绘制的数据。</p>';
 const lo=Math.min(0,...vals),hi=Math.max(0,...vals),span=hi-lo||1,top=28,bottom=244,left=76,width=650,plot=width-left-14;
 const y=v=>bottom-(v-lo)/span*(bottom-top),zero=y(0),group=plot/labels.length,bw=Math.min(44,group/(series.length+1));
 let svg=`<svg viewBox="0 0 ${width} 288" role="img" aria-label="${e(series.map(s=>s.name).join('、'))}，单位${e(unit)}"><text x="8" y="16">${e(unit)}</text>`;
 for(let t=0;t<=4;t++){const v=lo+span*t/4,yy=y(v);svg+=`<line x1="${left}" x2="${width-14}" y1="${yy}" y2="${yy}" class="fin-grid"/><text x="${left-9}" y="${yy+4}" text-anchor="end">${e(unit==='亿元'?amountNumber(v):number(v,Math.abs(v)<10?1:0))}</text>`;}
 labels.forEach((label,i)=>{svg+=`<text x="${left+group*(i+.5)}" y="273" text-anchor="middle">${e(label)}</text>`;series.forEach((s,j)=>{const v=s.values[i];if(typeof v!=='number'||!Number.isFinite(v))return;const x=left+group*(i+.5)+(j-series.length/2)*bw,yy=y(v);svg+=`<rect x="${x}" y="${Math.min(yy,zero)}" width="${bw-3}" height="${Math.max(1,Math.abs(yy-zero))}" rx="3" fill="${s.color||FIN_COLORS[j%4]}" tabindex="0"><title>${e(label)} · ${e(s.name)}：${e(unit==='亿元'?amountNumber(v):number(v,2))}${e(unit)}</title></rect>`;});});
 svg+='</svg>';
 return finLegend(series)+`<div class="fin-svg">${svg}</div><details class="fin-data"><summary>查看图表数值</summary>${marketTable(['期间',...series.map(s=>s.name+'（'+unit+'）')],labels.map((l,i)=>[l,...series.map(s=>s.values[i]==null?'—':unit==='亿元'?amountNumber(s.values[i]):number(s.values[i],2))]))}</details>`;
}
function finBars(rows,{unit='亿元',target=null,negative=false}={}){
 const finite=rows.filter(r=>typeof r.value==='number'&&Number.isFinite(r.value));
 const max=Math.max(1e-9,...finite.map(r=>Math.abs(r.value)),target??0)*1.12;
 return `<div class="fin-bars">${rows.map((r,i)=>{const ok=typeof r.value==='number'&&Number.isFinite(r.value),pct=ok?Math.abs(r.value)/max*100:0;
 return `<div class="fin-bar-row"><div class="fin-bar-label"><span>${e(r.label)}</span><strong>${ok?e(unit==='亿元'?amountNumber(r.value):number(r.value,2))+' '+e(unit):'无本息，不计算倍数'}</strong></div><div class="fin-bar-track ${negative?'signed':''}">${negative?'<span class="fin-zero"></span>':''}${ok?`<span class="fin-bar-fill" style="background:${r.color||FIN_COLORS[i%4]};width:${negative?pct/2:pct}%;${negative?'left:'+(r.value<0?50-pct/2:50)+'%;':''}"></span>`:''}${target!=null?`<span class="fin-target" style="left:${target/max*100}%" title="安全线 ${target}"></span>`:''}</div></div>`;}).join('')}</div>`;
}
function annualTrendVisual(a){
 const d=a.diagnostics||{},rows=d.profit_trend||[],cash=d.cash_reconciliation||[];
 if(rows.length<2)return '';
 const series=[{name:'营业收入',values:rows.map(r=>r.revenue==null?null:r.revenue/1e8)},{name:'净利润',values:rows.map(r=>r.net_profit==null?null:r.net_profit/1e8)},{name:'经营现金流',values:rows.map(r=>{const v=cash.find(c=>c.year===r.year)?.operating;return v==null?null:v/1e8;})}];
 return `<section class="card"><h2>${rows.length}期财报 · 经营变化</h2>${finFigure('收入、利润与现金是否同步',finColumns(rows.map(r=>r.year+'年'),series),'柱高使用同一金额尺度；可对照利润增长是否伴随经营现金增长。悬停柱形或展开数值查看详情。')}</section>`;
}
function annualDupontVisual(a){
 const d=a.diagnostics||{},attr=d.roe_attribution,raw=state.run?.raw_public||state.boot.data,history=raw?.financial_history||[];
 if(!attr)return '';
 const pair=[attr.from_year,attr.to_year].map(year=>history.find(r=>r.year===year)?.values);
 if(pair.some(v=>!v||v.revenue<=0||v.total_assets<=0||v.ending_equity<=0))return '';
 const factor=(v,i)=>[v.net_profit/v.revenue,v.revenue/v.total_assets,v.total_assets/v.ending_equity][i];
 const tiles=['净利率','总资产周转率','权益乘数'].map((name,i)=>`<article class="fin-factor"><h3>${name}</h3><p>${number(factor(pair[0],i)*(i===0?100:1),2)}${i===0?'%':'倍'} <span>→</span> <strong>${number(factor(pair[1],i)*(i===0?100:1),2)}${i===0?'%':'倍'}</strong></p><small>${i===0?'盈利水平':i===1?'资产使用效率':'财务杠杆'}</small></article>`).join('');
 const before=pair[0].net_profit/pair[0].ending_equity*100,after=pair[1].net_profit/pair[1].ending_equity*100;
 return `<section class="card"><h2>杜邦分析 · 回报变化来自哪里</h2><p>${attr.from_year} → ${attr.to_year}年，净资产收益率（ROE）从 <strong>${number(before,2)}%</strong> 变为 <strong>${number(after,2)}%</strong>。ROE＝净利率 × 总资产周转率 × 权益乘数。</p><div class="fin-factor-grid">${tiles}</div>${finFigure('三项因素对ROE变化的贡献',finBars(attr.contributions.map(c=>({label:c.label,value:c.value*100,color:c.value>=0?'#147d68':'#b17b31'})),{unit:'个百分点',negative:true}),'向右表示拉高ROE，向左表示拉低ROE；三项贡献合计为ROE变化。采用期末资产和权益及六种替换顺序平均归因，是代数解释，不代表因果。')}</section>`;
}
function annualForecastVisual(f){
 const h=f.history_prediction||{},p=h.future,v=h.validation;if(!p)return '';
 const d=state.run?.financial_analysis?.diagnostics,actual=d?.cash_reconciliation||[];
 const labels=[...actual.map(r=>r.year+'年'),p.target_year+'年（预测）'];
 const actuals=actual.map(r=>r.operating==null?null:r.operating/1e8);
 return finFigure('历史现金与下一年预测',finColumns(labels,[{name:'实际经营现金',values:[...actuals,null]},{name:'历史检验预测',values:[...actual.map(r=>r.year===v?.target_year?v.annual_operating/1e8:null),null],color:'#805aa0'},{name:'校正前预测',values:[...actual.map(()=>null),p.uncalibrated_operating/1e8],color:'#b17b31'},{name:'校正后预测',values:[...actual.map(()=>null),p.annual_operating/1e8],color:'#527fa7'}]),'最后一期为情景预测；历史检验预测仅使用其前两年数据。校正前后不代表置信区间，也没有逐月或长期预测。');
}
function annualFundingVisual(p){
 const f=p.funding,rows=p.composition.filter(c=>c.id!=='leasing').map(c=>({label:c.name+' · 本金',value:c.amount/1e8}));
 const gap=Math.max(0,f.unfunded_gap);const ratio=f.gap>0?Math.min(100,Math.max(0,(f.net_proceeds||0)/f.gap*100)):0;
 return `<section class="card"><h2>资金分配 · 需求覆盖</h2>${finFigure('各渠道分配了多少本金',finBars(rows),'各条使用同一金额尺度，未选渠道保留零值；本金包含用于支付手续费的部分。')}<div class="fin-coverage-label"><strong>净需求覆盖 ${number(ratio,1)}%</strong><span>净到账 ${money(f.net_proceeds)} / 需求 ${money(f.gap)}</span></div><div class="fin-coverage" role="img" aria-label="净需求覆盖${number(ratio,1)}%，未覆盖${e(money(gap))}"><span style="width:${ratio}%"></span></div><p>手续费 ${money(f.fees_due)}；尚未覆盖 ${money(gap)}。单一渠道足以满足条件时，不为展示组合而增加渠道。</p></section>`;
}
function annualRiskVisual(p){
 const risk=p.risk_evaluation,target=p.algorithm.target_dscr;
 return `<section class="card"><h2>压力测试 · 哪种情况最吃紧</h2><p><span class="fin-line-key"></span>虚线为偿债覆盖安全线 <strong>${number(target,2)}倍</strong>。每1元本息需要${number(target,2)}元预计可用于偿债的现金；条形越长，偿债余量越大。</p>${finFigure('各情景偿债覆盖倍数（DSCR）',finBars(risk.scenarios.map(s=>({label:s.label,value:s.dscr,color:s.passed?'#147d68':'#b17b31'})),{unit:'倍',target}),'绿色表示达到设定安全线，橙色表示未达到。未设置本息的情景不计算倍数；这里不是违约概率。')}</section>`;
}
