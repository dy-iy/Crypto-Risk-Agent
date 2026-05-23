from app.llm import call_llm_json
from app.prompts.classify_prompt import RISK_CATEGORIES, build_classify_prompt
from app.state import CryptoRiskState


KEYWORD_CATEGORY_MAP = {
    "链上漏洞 / 攻击风险": ["hack", "exploit", "attack", "漏洞", "攻击", "被盗", "drain"],
    "诈骗 / 跑路 / Rug Pull 风险": ["rug", "跑路", "诈骗", "抽走流动性", "无法提现"],
    "监管与法律风险": ["监管", "sec", "lawsuit", "调查", "起诉", "法律"],
    "交易所与系统运维风险": ["交易所", "exchange", "暂停提现", "宕机", "维护", "系统故障"],
    "稳定币异常风险": ["stablecoin", "usdt", "usdc", "dai", "脱锚", "depeg"],
    "爆仓 / 清算风险": ["爆仓", "清算", "liquidation", "margin"],
    "大额转账 / 巨鲸行为风险": ["巨鲸", "whale", "大额转账", "transfer"],
    "异常行情波动风险": ["暴跌", "暴涨", "异常波动", "闪崩", "dump", "pump"],
    "项目治理 / 团队异常风险": ["团队", "创始人", "治理", "dao", "离职", "失联"],
    "偿付能力 / 储备 / 流动性风险": ["储备", "流动性", "insolvency", "资不抵债", "挤兑"],
    "基础设施 / 协议层异常风险": ["共识", "节点", "桥", "oracle", "预言机", "协议"],
    "宏观 / 政策冲击风险": ["加息", "宏观", "政策", "关税", "禁令"],
}


def _heuristic_categories(text: str, signals: list[str]) -> list[str]:
    haystack = f"{text} {' '.join(signals)}".lower()
    categories: list[str] = []
    for category, keywords in KEYWORD_CATEGORY_MAP.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            categories.append(category)
    return categories[:4]


def classify_agent(state: CryptoRiskState) -> CryptoRiskState:
    cleaned_text = state.get("cleaned_text", "")
    risk_signals = state.get("risk_signals", [])
    prompt = build_classify_prompt(cleaned_text, risk_signals)
    llm_result = call_llm_json(prompt)

    llm_categories = llm_result.get("risk_categories", [])
    if not isinstance(llm_categories, list):
        llm_categories = []

    valid_categories = [category for category in llm_categories if category in RISK_CATEGORIES]
    risk_categories = valid_categories or _heuristic_categories(cleaned_text, risk_signals)
    if state.get("has_risk") and not risk_categories:
        risk_categories = ["异常行情波动风险"]

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["classify_agent"] = llm_result

    return {
        **state,
        "risk_categories": risk_categories,
        "raw_agent_outputs": raw_outputs,
    }
