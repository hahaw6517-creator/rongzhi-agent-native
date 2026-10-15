"""Revalidate saved market evidence without claiming a fresh search or model call."""
from copy import deepcopy
from finbridge.market_rules import market_decision


def attach_saved_evidence(engine,parent):
    previous=parent.get("outputs",{}).get("analyze_industry_region",{})
    sources=deepcopy(previous.get("sources",[]))
    if not sources:return
    signals=[{k:s[k] for k in ("kind","source_id","quote","scope") if k in s} for s in previous.get("market_decision",{}).get("accepted_signals",[])]
    def analyzer(data,profile,outputs):
        from finbridge.industry_context import context_placeholder
        result=context_placeholder(data,profile,status="历史公开来源重新核验",message="本版未重新联网或调用模型；沿用历史公开来源并重新核验时效和适用规则，历史模型解释不代替本版分析。")
        result.update(sources=sources,source_status="沿用"+str(len(sources))+"条历史来源；没有新检索或新模型解释",
            market_decision=market_decision(data,profile,outputs,sources,signals),available=False)
        return result
    engine.industry_analyzer=analyzer
    engine.result["mode"]="本地重算 · 历史证据重新核验"
