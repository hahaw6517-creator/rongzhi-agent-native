"""Model-driven public-data decisions over an explicit dependency graph."""
from copy import deepcopy
from finbridge.workflow import DiligenceRun, TOOLS, fingerprint, LABELS
from finbridge.public_data import public_only, PUBLIC_LABELS
from finbridge.public_finance import prepare_public
from finbridge.public_portfolio import build_public_portfolio, verify_public_plan
from finbridge.market_rules import effective_portfolio
from finbridge.task_focus import build_task_focus


class PublicDecisionRun(DiligenceRun):
    def __init__(self,data,profile,goal,source):
        raw=public_only(data)
        derived,settings,model=prepare_public(raw,profile)
        super().__init__(derived,settings,goal,source)
        self.raw_public=raw
        self.model=model
        self.result.update(public_analysis=model,raw_public=raw,input_profile=deepcopy(profile),fingerprint=fingerprint(raw,profile))
        self.tools=dict(TOOLS)
        self.tools["estimate_financing_need"]=("自主推导融资需求",("inspect_data","calculate_ratios"),"仅从公开报表计算净营运资本、现金外推、投资和到期压力，列出融资缺口及每项公式、代理口径和情景假设。")
        self.tools["verify_decision"]=("独立复算与验证决策",("optimize_financing_portfolio","analyze_industry_region"),"独立重新计算月供及年度本息，检查资金闭合、现金压力及杠杆约束；不满足时明确暴露缺口。")
        if profile.get("requested_amount") is not None:
            self.tools["review_financing_request"]=("复审需求并求解替代方案",("verify_decision",),"核对用户需求与公开历史用途、负债及现金压力；不匹配时改变金额或期限重新求解，独立验证替代方案并说明原因，不能只劝用户再借钱。")
            self.tools["match_routes"]=("匹配中小微与科创产品",TOOLS["match_routes"][1],"按用途、地区和自报企业类型筛选官方产品登记；公开产品上限不是企业授信，认证及担保条件未知时明确标注。")
        label,deps,description=self.tools["simulate_repayment"]
        self.tools["simulate_repayment"]=(label,(*deps,"estimate_financing_need"),description)
        label,deps,description=self.tools["optimize_financing_portfolio"]
        self.tools["optimize_financing_portfolio"]=(label,(*deps,"estimate_financing_need"),"调用公开现金模型，按用户需求与用途匹配官方中小微融资产品边界，求解金额和还款结构；产品准入和额度仍待银行确认。")
        label,deps,description=self.tools["prepare_deliverables"]
        self.tools["prepare_deliverables"]=(label,(*deps,"verify_decision",*(("review_financing_request",) if "review_financing_request" in self.tools else ())),description)

    def _dispatch(self,name):
        out=self.result["outputs"]
        if name=="retrieve_knowledge" and self.profile.get("requested_amount") is not None:
            from finbridge.sme_channels import match_sme_channels
            channels=match_sme_channels(self.raw_public,self.profile)
            return dict(query="中小微与科创："+self.profile.get("requested_purpose","经营周转"),
                documents=[dict(id="PRODUCT-"+c["id"],title=c["name"],publisher=c["provider"],date=c["published_on"] or "页面未注明发布日期",url=c["url"],
                    content=c["published_terms"],conditions=c["conditions"],checked_on=c["checked_on"],status=c["status"]) for c in channels if c["scope_match"]],
                note="人工核验的官方产品知识库，与近期市场证据分开；产品资料不证明企业已经准入。超过90天的资料不参与数值配置。")
        if name=="inspect_data":
            m=self.model
            return dict(blocked=not m["available"],invalid=m["invalid"],issues=m["issues"],core_missing=m["missing"],missing=m["missing"],
                period_known=m["period_known"],coverage=round(100*(1-len(m["missing"])/max(1,len(PUBLIC_LABELS)))),note="只统计公开科目；缺失不补零。")
        if name=="calculate_ratios":
            from finbridge.analysis import calculate_deep_metrics
            # Accurate contract DSCR, overdue ratios and eligible collateral are unavailable.
            raw={k:v for k,v in self.data.items() if k not in {"cash_flow_available_for_debt_service","scheduled_debt_service","financing_need","available_internal_funds"}}
            ratios=calculate_deep_metrics(raw)
            for key in ("dscr","financing_gap","overdue_receivables_ratio","receivables_over_90_ratio"):
                ratios.pop(key,None)
            for key,value in ratios.items():
                value["label"]=LABELS.get(key,key)
                value["kind"]="财务指标计算"
            for key,label in PUBLIC_LABELS.items():
                if self.raw_public.get(key) is not None:
                    ratios[key]=dict(label="公开原值："+label,value=self.raw_public[key],unit="元",formula="公开报表原值，无需计算",sources=[key],
                        period="公开比较期（上期）" if key.startswith(("prior_","beginning_")) else self.raw_public.get("report_period","未提供"),data_issue=None,kind="公开原值")
            for entry in self.model["ledger"]:
                key="public_"+entry["key"]
                ratios[key]=dict(label=entry["label"]+"（"+entry["kind"]+"）",value=entry["value"],unit="%" if entry["key"]=="growth" else "元",formula=entry["formula"],
                    sources=entry["sources"],period=self.raw_public.get("report_period", "未提供"),data_issue=None,kind=entry["kind"])
            return ratios
        if name=="estimate_financing_need":return deepcopy(self.model)
        if name=="assess_risk":
            from finbridge.risk import analyze_financial_risk
            raw={k:v for k,v in self.data.items() if k not in {"cash_flow_available_for_debt_service","scheduled_debt_service"}}
            risk=analyze_financial_risk(raw)
            m=self.model
            if m["available"] and m["service"]>0:
                value=m["cash"]/m["service"]
                risk["dimensions"]["debt_service"]={"label":"现金偿付能力（公开数据代理）","risk_level":"较高" if value<1 else "关注" if value<m["assumptions"]["target_coverage"] else "暂未触发演示规则",
                    "data_sufficiency":"公开科目满足代理情景；不是合同DSCR",
                    "evidence":[{"metric":"公开现金代理 / 存量本息代理","value":value,"unit":"倍","period":self.raw_public["report_period"],
                        "rule":"public_proxy_coverage","rule_label":"年度现金代理低于现有本息代理的安全余量","triggered":value<m["assumptions"]["target_coverage"]}]}
            if self.profile.get("requested_amount") is not None:
                from finbridge.sme_decision import financial_health
                risk["plain_summary"]=financial_health(self.raw_public)
            return risk
        if name=="simulate_repayment":
            from finbridge.decision import annual_annuity_factor
            m=self.model;a=m["assumptions"];scenarios=[]
            if m["available"]:
                stressed=m["cash"]*(1-a["cash_drop"]) if m["cash"]>=0 else m["cash"]*(1+a["cash_drop"])
                for months in (12,24,36,60):
                    amount=self.profile.get("requested_amount",m["gap"])
                    new_service=amount*annual_annuity_factor(a["assumed_rate"]+a["rate_up"],months)*min(12,months)/12
                    total=new_service+m["service"]
                    scenarios.append(dict(scenario=f"全部缺口按{months}个月等额本息",months=months,new_annual_service=new_service,
                        cfads=stressed,existing_annual_service=m["service"],dscr=stressed/total if total>0 else None,
                        assumed_rate=a["assumed_rate"]+a["rate_up"],cash_drop=a["cash_drop"],
                        passes_cash=stressed+1e-7>=a["target_coverage"]*total))
            return dict(available=m["available"],gap=self.profile.get("requested_amount",m.get("gap")),scenarios=scenarios,note="单一期限等额本息对照，只用于比较期限压力，不代表已匹配产品；最终求解按各候选产品的保守还款方式和全期限本息峰值检验。",missing_reason="公开科目不足" if not m["available"] else None)
        if name=="match_routes":
            if self.profile.get("requested_amount") is not None:
                from finbridge.sme_channels import match_sme_channels
                return match_sme_channels(self.raw_public,self.profile)
            rows=[]
            for scenario in out["simulate_repayment"]["scenarios"]:
                n=scenario["months"]
                purpose_ok=n>24 or self.model["working_gap"]>=self.model["gap"]-.01
                rows.append(dict(name=f"{n}个月分期借款情景",status="单一期限现金压力通过，仍须检验组合与杠杆" if scenario["passes_cash"] and purpose_ok else "该期限不能覆盖全部用途" if not purpose_ok else "全缺口借款未通过现金压力线",
                    evidence=[f"新增一年内加息本息{scenario['new_annual_service']:.2f}元",f"现金代理覆盖倍数{scenario['dscr']:.3f}" if scenario["dscr"] is not None else "无正本息负担", "投资用途须使用匹配的中长期结构"],conditions=["后续优化还需满足杠杆及用途约束；实际审批另行确认"],materials=[],source="KB-001",subtitle="数学情景，不是金融产品"))
            return rows
        if name=="optimize_financing_portfolio":
            p=build_public_portfolio(self.raw_public,self.profile)
            p["task_focus"]=build_task_focus(self.data,self.profile,out,self.result["goal"],p)
            return p
        if name=="verify_decision":return verify_public_plan(effective_portfolio(out))
        if name=="review_financing_request":
            from finbridge.sme_decision import review_and_adjust
            return review_and_adjust(effective_portfolio(out),self.raw_public,self.profile)
        if name=="prepare_deliverables":
            p=effective_portfolio(out);v=out["verify_decision"]
            review=out.get("review_financing_request")
            recommended_verification=v;recommended_from="原期限下的条件式方案"
            focus_profile=self.profile
            if review and (review.get("alternative") or {}).get("verified"):
                from finbridge.sme_decision import recommended_portfolio
                p=recommended_portfolio(out)
                recommended_verification=review["alternative"]["verification"]
                recommended_from="复审后另行求解的调整方案"
                focus_profile={**self.profile,"requested_months":review["alternative"]["months"]}
            focus=build_task_focus(self.data,focus_profile,out,self.result["goal"],p)
            tasks=[dict(id="ACT-001",title="核对公开报表同主体、同年度、同合并口径及页码",owner="使用者",priority="优先",evidence="公开原始数据",completed=False),
                dict(id="ACT-002",title="复核情景增长、资本开支、留存天数和利率，必要时重新求解",owner="使用者",priority="优先",evidence="模型假设",completed=False)]
            if p["funding"].get("unfunded_gap",0):
                tasks.append(dict(id="ACT-003",title="比较缩减投资、延后支出或非债务资金的路径",owner="使用者",priority="优先",evidence="未覆盖现金缺口",completed=False))
            if review:
                tasks += [dict(id=f"CH-{i+1}",title=c["name"]+"：确认"+"、".join(c["conditions"]),owner="使用者与受理机构",priority="申请前",evidence=c["url"],completed=False) for i,c in enumerate(p["composition"]) if (c.get("amount") or 0)>0]
            return dict(task_focus=focus,request_review=review,recommended_from=recommended_from,recommended_verification=recommended_verification,
                readiness=recommended_verification["status"],findings=[focus["summary"],recommended_verification["note"]],tasks=tasks,drivers=[],
                limitations=[self.model["note"],"公开报表不能给出真实授信、合格债权、担保物可用额度和合同DSCR。", "模型支持完整年度非金融企业报表；财务报表重述、季节性和现金流分类差异仍需核对。"])
        return super()._dispatch(name)

    def local(self,progress=None):
        order=["inspect_data","calculate_ratios","estimate_financing_need","assess_risk","retrieve_knowledge","simulate_repayment","match_routes","optimize_financing_portfolio","analyze_industry_region","verify_decision"]
        if "review_financing_request" in self.tools:order.append("review_financing_request")
        for name in (*order,"prepare_deliverables"):
            if name not in self.result["outputs"]:
                self.execute(name)
                if progress:progress(self.result["events"][-1])
        return self.finish()
