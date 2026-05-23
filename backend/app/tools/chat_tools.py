import re

from app.state import CryptoRiskState


EXCHANGES = ["Binance", "OKX", "Coinbase", "Bybit", "Kraken", "Huobi", "Gate", "Bitget"]
CHAINS = ["Ethereum", "BSC", "BNB Chain", "Solana", "Bitcoin", "Tron", "Polygon", "Arbitrum", "Optimism"]

CATEGORY_IMPACT_MAP = {
    "链上漏洞 / 攻击风险": ["协议资金池、用户钱包或跨链桥资产可能受损", "相关代币信任度和流动性可能下降"],
    "诈骗 / 跑路 / Rug Pull 风险": ["投资者本金安全受到威胁", "项目代币可能出现流动性枯竭或价格剧烈下跌"],
    "监管与法律风险": ["项目、交易所或相关代币可能面临合规限制", "用户交易、提现或服务可用性可能受到影响"],
    "交易所与系统运维风险": ["用户提现、交易撮合或资产访问可能短期受阻", "市场信心和平台流动性可能下降"],
    "稳定币异常风险": ["稳定币锚定关系可能失衡", "DeFi 抵押、借贷和交易对可能出现连锁影响"],
    "爆仓 / 清算风险": ["高杠杆头寸可能集中清算", "市场波动可能进一步放大"],
    "大额转账 / 巨鲸行为风险": ["市场可能解读为潜在抛压或资金迁移", "短期价格和流动性可能受到冲击"],
    "异常行情波动风险": ["短期交易滑点和波动风险上升", "杠杆用户可能面临更高保证金压力"],
    "项目治理 / 团队异常风险": ["项目执行和治理稳定性可能下降", "社区信心可能受到影响"],
    "偿付能力 / 储备 / 流动性风险": ["提现兑付能力和资产储备可信度可能受质疑", "可能引发挤兑或流动性紧张"],
    "基础设施 / 协议层异常风险": ["链上应用、节点服务或预言机依赖可能受影响", "协议可用性和交易确认可能异常"],
    "宏观 / 政策冲击风险": ["整体风险偏好可能下降", "加密资产市场可能受到外部政策或宏观变量冲击"],
}

BANNED_TERMS = ["买入", "卖出", "做空", "梭哈"]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _detect_input_type(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["hack", "exploit", "漏洞", "攻击", "被盗"]):
        return "链上安全事件"
    if any(word in lowered for word in ["rug", "跑路", "诈骗", "无法提现"]):
        return "诈骗或跑路事件"
    if any(word in lowered for word in ["exchange", "交易所", "宕机", "暂停提现"]):
        return "交易所异常"
    if any(word in lowered for word in ["stablecoin", "usdt", "usdc", "脱锚", "depeg"]):
        return "稳定币异常"
    if any(word in lowered for word in ["whale", "巨鲸", "大额转账", "transfer"]):
        return "链上大额转账"
    if any(word in lowered for word in ["公告", "governance", "dao", "团队", "创始人"]):
        return "项目事件或公告"
    return "加密货币风险文本"


def prepare_chat_input(state: CryptoRiskState) -> CryptoRiskState:
    original_text = state.get("original_text", "")
    cleaned_text = " ".join(original_text.split())

    wallet_addresses = re.findall(r"0x[a-fA-F0-9]{40}|T[A-Za-z0-9]{33}|bc1[a-zA-Z0-9]{25,62}", cleaned_text)
    tickers = re.findall(r"(?<![A-Za-z0-9])\$?[A-Z]{2,10}(?![A-Za-z0-9])", cleaned_text)
    exchanges = [name for name in EXCHANGES if name.lower() in cleaned_text.lower()]
    chains = [name for name in CHAINS if name.lower() in cleaned_text.lower()]
    input_type = _detect_input_type(cleaned_text)

    entities = {
        "projects": [],
        "tokens": _dedupe([ticker.lstrip("$") for ticker in tickers]),
        "exchanges": _dedupe(exchanges),
        "wallet_addresses": _dedupe(wallet_addresses),
        "chains": _dedupe(chains),
    }

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["input_tool"] = {"input_type": input_type, "entities": entities}

    return {
        **state,
        "cleaned_text": cleaned_text,
        "input_type": input_type,
        "entities": entities,
        "raw_agent_outputs": raw_outputs,
    }


def build_impact(state: CryptoRiskState) -> CryptoRiskState:
    impacts: list[str] = []
    for category in state.get("risk_categories", []):
        impacts.extend(CATEGORY_IMPACT_MAP.get(category, []))

    if not impacts and state.get("has_risk"):
        impacts = ["相关资产、用户资金安全或市场情绪可能受到影响"]

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["impact_tool"] = {"impact": impacts}

    return {
        **state,
        "impact": list(dict.fromkeys(impacts))[:6],
        "raw_agent_outputs": raw_outputs,
    }


def _sanitize_advice(items: list[str]) -> list[str]:
    return [item for item in items if not any(term in item for term in BANNED_TERMS)]


def build_advice(state: CryptoRiskState) -> CryptoRiskState:
    categories = state.get("risk_categories", [])
    advice = [
        "降低相关资产和平台的风险暴露，避免在信息未核实前追加资金。",
        "核实项目方、交易所或链上浏览器的官方公告，确认事件范围和时间线。",
        "持续关注链上资金流向、提现状态、流动性变化和社区治理动态。",
    ]

    if "链上漏洞 / 攻击风险" in categories:
        advice.append("暂停与可疑合约交互，检查授权额度并评估是否需要撤销高风险授权。")
    if "诈骗 / 跑路 / Rug Pull 风险" in categories:
        advice.append("优先核查流动性池、团队钱包和项目官方渠道，警惕二次钓鱼链接。")
    if "稳定币异常风险" in categories:
        advice.append("关注稳定币锚定价格、赎回通道、储备披露和主要交易对深度。")
    if "交易所与系统运维风险" in categories:
        advice.append("关注平台提现、充值、撮合和客服公告，避免在系统异常期间进行高风险操作。")
    if "大额转账 / 巨鲸行为风险" in categories:
        advice.append("跟踪大额地址后续流向，区分交易所充值、冷钱包归集和潜在抛压。")

    advice = _sanitize_advice(list(dict.fromkeys(advice)))[:7]
    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["advice_tool"] = {"advice": advice}

    return {
        **state,
        "advice": advice,
        "raw_agent_outputs": raw_outputs,
    }
