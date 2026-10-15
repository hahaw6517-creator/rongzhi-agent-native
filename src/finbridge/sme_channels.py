"""Small, curated official product register. Product maxima are NOT available credit."""
from copy import deepcopy
from datetime import date

REGISTER = [
    dict(id="credit",name="建行小微企业信用快贷",provider="中国建设银行",region="全国（以当地受理为准）",
        purposes=["经营周转","订单备货","研发周转"],maximum=5_000_000.,max_months=12,min_months=1,
        repayment="bullet",published_terms="官方上限500万元、最长12个月；随借随还，按实际使用计息。",
        conditions=["小微企业准入及征信", "企业网银或手机银行签约", "建行金融资产或诚信纳税条件"],
        url="https://scompany.ccb.com/cn/home/smallcompany/index2.html",checked_on="2026-10-13",published_on=None),
    dict(id="receivable",name="建行小微企业平台快贷",provider="中国建设银行",region="全国（须接入合作平台）",
        purposes=["经营周转","订单备货","研发周转"],maximum=5_000_000.,max_months=36,min_months=1,
        repayment="bullet",published_terms="官方上限500万元、最长36个月；具体期限以合作平台产品为准。",
        conditions=["属于建行合作电商、政府或供应链平台客群", "小微企业准入及征信", "具体用途、单笔期限与还款方式须确认"],
        url="https://scompany.ccb.com/cn/home/smallcompany/index2.html",checked_on="2026-10-13",published_on=None),
    dict(id="secured",name="建行小企业额度抵押贷款",provider="中国建设银行",region="全国（以当地受理为准）",
        purposes=["经营周转","订单备货","设备购置","研发周转"],maximum=None,max_months=36,min_months=1,
        repayment="equal_principal",published_terms="单笔最长3年，支持经营周转及设备投资；可按月或按季等额还本。",
        conditions=["有合格可抵押资产及处分权", "银行核准抵押价值和融资比例", "企业经营、征信及自有资金条件"],
        url="https://company.ccb.com/cn/home/company/gsyw/560019.html",checked_on="2026-10-13",published_on=None),
    dict(id="leasing",name="建行小企业固定资产购置贷款（设备）",provider="中国建设银行",region="全国（以当地受理为准）",
        purposes=["设备购置"],maximum=None,max_months=60,min_months=36,
        repayment="equal_principal",published_terms="机器设备购置期限3至5年；可分期还本。测算采用按月等额本金假设。",
        conditions=["真实设备购置项目", "项目自有资金比例达到银行要求", "抵质押或符合银行要求的保证担保"],
        url="https://group2.ccb.com/cn/home/company/gsyw/560024.html",checked_on="2026-10-13",published_on=None),
    dict(id="boc_tech",name="中行科创贷",provider="中国银行",region="全国（以当地受理为准）",
        purposes=["经营周转","订单备货","研发周转"],maximum=None,max_months=None,min_months=None,repayment="unknown",
        published_terms="官方明确支持科技小微、专精特新和高新技术企业；本来源未披露统一期限和额度上限。",
        conditions=["科技小微企业准入", "专精特新、高新技术等资格由银行核验", "额度、用途、利率、期限及还款方式须取得具体产品信息"],
        url="https://www.boc.cn/aboutboc/bi1/202412/t20241223_25228847.html",checked_on="2026-10-13",published_on="2024-12-23"),
    dict(id="sip_tech",name="SIP科贷通",provider="苏州工业园区合作银行及担保机构",region="苏州工业园区",
        purposes=["经营周转","研发周转","订单备货"],maximum=None,max_months=36,min_months=1,repayment="bullet",
        published_terms="贷款期限延长至3年；按科创指数或园区创新积分分档准入与定额，不能由财报推断积分。",
        conditions=["注册及项目在苏州工业园区范围", "科创指数准入或园区创新积分≥50且科创指数暂无分", "合作银行审批及合作担保机构承接"],
        url="https://www.suzhou.gov.cn/szsrmzf/szyw/202608/d9694b09d8964dc2b2aee55db67039e8.shtml",checked_on="2026-10-13",published_on="2026-08-13"),
    dict(id="boc_js_tech",name="中行小微速贷·科创贷（江苏平台登记）",provider="中国银行／江苏省中小企业公共服务平台",region="江苏",
        purposes=["经营周转","订单备货","研发周转"],maximum=10_000_000.,max_months=12,min_months=1,repayment="bullet",
        published_terms="江苏平台登记上限1000万元、期限1年，信用为主；参考利率不是本企业报价，本模型不直接采用。",
        conditions=["科技型小微、创新型中小或专精特新等产品准入", "银行核验科技属性和征信", "具体授信、增信与报价以江苏受理机构为准"],
        url="https://www.smejs.cn/fin_pro_show.aspx?finproid=62",checked_on="2026-10-13",published_on=None),
]


def match_sme_channels(data,profile):
    purpose=profile.get("requested_purpose","经营周转");region=str(data.get("region",""))
    tech=profile.get("enterprise_type")=="科创企业"
    today=date.today();rows=[]
    for item in REGISTER:
        row=deepcopy(item)
        local_ok=("苏州" in region and "工业园区" in region) if row["id"]=="sip_tech" else ("江苏" in region or any(city in region for city in ("苏州","南京","无锡","常州","南通","扬州","镇江","徐州","盐城","泰州","宿迁","淮安","连云港"))) if row["id"]=="boc_js_tech" else True
        customer_ok=row["id"] not in {"sip_tech","boc_tech","boc_js_tech"} or tech
        row["scope_match"]=local_ok and customer_ok and purpose in row["purposes"]
        row["source_age_days"]=(today-date.fromisoformat(row["checked_on"])).days
        row["source_current"]=0<=row["source_age_days"]<=90
        row["status"]="候选渠道 · 企业资格待核验" if row["scope_match"] and row["source_current"] else "来源需重新核验" if row["scope_match"] else "不适用于当前用途、地区或客群"
        row["eligible"]=None  # A financial statement cannot prove bank or government eligibility.
        row["quoted_rate"]=None;row["approved_limit"]=None
        row["reason"]=("与填写用途和服务客群方向相符；" if row["scope_match"] else "未匹配当前用途或服务范围；")+"产品上限不等于本企业授信，财报不能确认征信、税务、积分、平台或抵押资格。"
        row["application_step"]="通过官方页面联系当地企业金融网点，确认准入、具体报价和还款表后再决定申请。"
        rows.append(row)
    return rows
