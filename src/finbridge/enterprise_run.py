"""Enterprise workflow with distinct financial, decision, risk and report outputs."""
from copy import deepcopy
from finbridge.public_run import PublicDecisionRun
from finbridge.enterprise_model import (
    ENGINE, financial_analysis, product_rules, optimize_financing,
    verify_plan, review_request, evaluate_risk,
)
from finbridge.market_rules import effective_portfolio


class EnterpriseDecisionRun(PublicDecisionRun):
    def __init__(self,data,profile,goal,source):
        # The request is mandatory in the new UI; missing request becomes an estimate,
        # never a silent request to run the previous SME workflow.
        profile={**profile,"decision_engine":ENGINE}
        if profile.get("requested_amount") is None:
            profile["requested_amount"]=100000.
        super().__init__(data,profile,goal,source)
        self.result["decision_engine"]=ENGINE
        self.tools={
            "inspect_data":("核验财报原值",(),"检查完整性、同年度口径和报表勾稽。缺失不补零。"),
            "calculate_ratios":("计算财务指标",("inspect_data",),"Python计算流动性、盈利、杠杆、营运和现金质量指标，保留公式与来源。"),
            "estimate_financing_need":("财务诊断与现金流预测",("calculate_ratios",),"结合指标诊断利润兑现、回款占用、负债空间与融资需求匹配；生成逐月现金情景和模拟区间。"),
            "match_routes":("通用融资产品规则筛选",("estimate_financing_need",),"匹配信用贷款、抵押经营贷款、应收质押贷款、设备租赁，按用途、期限和非重复资产池筛选。"),
            "optimize_financing_portfolio":("MILP＋CVaR双目标规划",("match_routes",),"先最大覆盖净用款，再平衡利息费用与95%尾部现金缺口，真实求解三种风险权重。"),
            "analyze_industry_region":("近期行业地区证据",("optimize_financing_portfolio",),"如启用AI，检索与核验近期原站资料；数值变化只能触发Python敏感性重算。"),
            "assess_risk":("蒙特卡洛与逆向压力测试",("analyze_industry_region",),"用3000条独立路径检验现金不足和储备不足，二分查找现金下降、加息的安全临界点。"),
            "verify_decision":("独立复算与方案验证",("assess_risk",),"独立展开本金、利息、费用和全期限滚动本息，检查资金闭合及规则边界。"),
            "review_financing_request":("需求复审与调整建议",("verify_decision",),"原需求无法覆盖时，以可支持净用款重新求解替代方案并验证；等待用户确认是否更新。"),
            "prepare_deliverables":("提炼决策报告",("review_financing_request",),"从财务、组合、风险中提取关键发现、策略与行动；不复制详细模块。"),
        }

        if self.profile.get('decision_scope')=='working-capital-12m':
            for key,label,description in [('estimate_financing_need','财务诊断与一年现金预测','三年诊断、一次历史检验与误差校正，只预测下一完整年度。'),('match_routes','一年期周转产品筛选','信用、抵押流动资金贷款及应收质押贷款；不配置设备租赁，不默认续贷。'),('optimize_financing_portfolio','一年期MILP组合决策','先最大覆盖净需求，再最小化一年成本；现金、杠杆、经营用途及支付时点敏感性约束。'),('assess_risk','一年期情景压力检验','明确说明现金、回款、毛利率和利率变化；固定组合验证，不估计违约概率。')]:
                if key in self.tools:self.tools[key]=(label,self.tools[key][1],description)

    def _dispatch(self,name):
        out=self.result["outputs"]
        if name=="estimate_financing_need":
            analysis=financial_analysis(self.raw_public,self.profile,out["calculate_ratios"])
            self.result["financial_analysis"]=analysis
            return {**deepcopy(self.model),"financial_diagnosis":analysis}
        if name=="match_routes":return product_rules(self.raw_public,self.profile,self.model)
        if name=="optimize_financing_portfolio":
            return optimize_financing(self.raw_public,self.profile,selection_objective=self.profile.get('optimization_strategy','balanced'))
        if name=="assess_risk":
            p=effective_portfolio(out)
            return dict(dimensions={},plain_summary=self.result.get("financial_analysis",{}).get("findings",[]),
                enterprise_risk=p.get("risk_evaluation") or evaluate_risk(p))
        if name=="verify_decision":return verify_plan(effective_portfolio(out))
        if name=="review_financing_request":return review_request(effective_portfolio(out),self.raw_public,self.profile)
        if name=="prepare_deliverables":
            p=effective_portfolio(out);risk=out["assess_risk"]["enterprise_risk"];v=out["verify_decision"]
            diagnoses=self.result.get("financial_analysis",{}).get("findings",[])
            deep=self.result.get('financial_analysis',{}).get('diagnostics') or {}
            takeaways=[dict(title=d['title'],finding=d['evidence'],implication=d['implication']) for d in diagnoses[:3]]
            attribution=deep.get('roe_attribution')
            if attribution:
                biggest=max(attribution['contributions'],key=lambda x:abs(x['value']))
                takeaways[1:2]=[dict(title='盈利变化来源',finding=f"{attribution['from_year']}—{attribution['to_year']}年期末权益回报变化{attribution['change']*100:.2f}个百分点，主要代数分项为{biggest['label']}（{biggest['value']*100:.2f}个百分点）。",implication='利润率、效率与杠杆贡献分开判断；这不是因果识别，增加负债不能代替经营改善。')]
            support=deep.get('support')
            if support:takeaways.append(dict(title='现金支持与融资约束',finding=f"基准经营现金{support.get('financing_base_ocf',support['base_ocf'])/1e8:,.6f}亿元；诊断保守情景{support.get('financing_conservative_ocf',support['conservative_ocf'])/1e8:,.6f}亿元。最紧情景为{support['binding_scenario']}。",implication='扣除维持性投资后进入融资现金约束，与用户压力假设取更严格者；这是可复算情景，不是未来现金承诺。'))
            if self.profile.get('decision_scope')=='working-capital-12m':
                takeaways=[dict(title=x['title'],finding=x['text'],implication=x['decision_link']) for x in self.result['financial_analysis'].get('year_diagnosis',[])]
            summary=p.get("decision_summary",{})
            tasks=[dict(id=f"ACT-{i+1:03d}",title=x,owner="使用者",priority="优先",evidence="模型与风险验证",completed=False)
                   for i,x in enumerate(summary.get("actions",[]))]
            report=dict(title=summary.get("title",p["status"]),conclusion=summary.get("text",p["status"]),
                financial_takeaways=takeaways,
                decision=dict(net=p["funding"].get("net_proceeds",0),principal=p["funding"]["debt_total"],gap=p["funding"]["unfunded_gap"],
                    interest=p["funding"]["total_assumed_interest"],fees=p["funding"]["fees_due"],
                    products=[dict(name=c["name"],amount=c["amount"],months=c["months"]) for c in p["composition"] if c["amount"]>.01]),
                risk=dict(cvar=risk.get("cvar"),cash_probability=risk.get("cash_shortfall_probability"),reverse=risk.get("reverse_summary"),
                    label="需调整后复核" if not v["passed"] else "在列明假设下通过"),
                verification=v,actions=summary.get("actions",[]),assumptions=p["algorithm"].get("assumptions",[]),
                note="报告仅提炼当前分析版本。替代方案需用户确认后才更新，不自动替换原需求。")
            self.result["decision_report"]=report
            if self.profile.get('decision_scope')=='working-capital-12m':
                report['annual_scope']=True;report['forecast']=self.model.get('cash_prediction');report['risk_scenarios']=risk.get('scenarios',[])
                report['assumptions']=['规划期限固定12个月，资金用途固定生产经营周转。','未来现金只预测下一完整年度；历史误差50%转移并限幅是显式假设，不能证明提高准确率。',p['annual_context']['note'],p['repayment_note']]
            return dict(readiness=v["status"],recommended_verification=v,request_review=out["review_financing_request"],
                recommended_from="当前需求下的已求解方案",findings=[report["conclusion"]],tasks=tasks,drivers=[],
                task_focus=dict(summary=report["conclusion"],comparison=dict(options=[])),
                limitations=report["assumptions"])
        return super()._dispatch(name)

    def local(self,progress=None):
        for name in self.tools:
            if name not in self.result["outputs"]:
                self.execute(name)
                if progress:progress(self.result["events"][-1])
        return self.finish()
