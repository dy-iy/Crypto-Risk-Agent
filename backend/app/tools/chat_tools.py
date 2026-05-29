import re

from app.state import CryptoRiskState


COINS = [
    {"symbol": "BTC", "terms": ["BTC", "$BTC", "Bitcoin", "比特币", "大饼"]},
    {"symbol": "ETH", "terms": ["ETH", "$ETH", "Ethereum", "Ether", "以太坊"]},
    {"symbol": "USDT", "terms": ["USDT", "$USDT", "Tether", "泰达币"]},
    {"symbol": "BNB", "terms": ["BNB", "$BNB", "Binance Coin", "币安币"]},
    {"symbol": "SOL", "terms": ["SOL", "$SOL", "Solana", "索拉纳"]},
    {"symbol": "USDC", "terms": ["USDC", "$USDC", "USD Coin", "Circle USD"]},
    {"symbol": "XRP", "terms": ["XRP", "$XRP", "Ripple", "瑞波币", "瑞波"]},
    {"symbol": "DOGE", "terms": ["DOGE", "$DOGE", "Dogecoin", "狗狗币"]},
    {"symbol": "TON", "terms": ["TON", "$TON", "Toncoin", "The Open Network", "吨币"]},
    {"symbol": "ADA", "terms": ["ADA", "$ADA", "Cardano", "艾达币", "卡尔达诺"]},
    {"symbol": "TRX", "terms": ["TRX", "$TRX", "TRON", "波场"]},
    {"symbol": "AVAX", "terms": ["AVAX", "$AVAX", "Avalanche", "雪崩"]},
    {"symbol": "SHIB", "terms": ["SHIB", "$SHIB", "Shiba Inu", "柴犬币"]},
    {"symbol": "LINK", "terms": ["LINK", "$LINK", "Chainlink", "链环"]},
    {"symbol": "DOT", "terms": ["DOT", "$DOT", "Polkadot", "波卡"]},
    {"symbol": "BCH", "terms": ["BCH", "$BCH", "Bitcoin Cash", "比特币现金"]},
    {"symbol": "LTC", "terms": ["LTC", "$LTC", "Litecoin", "莱特币"]},
    {"symbol": "NEAR", "terms": ["NEAR", "$NEAR", "Near Protocol"]},
    {"symbol": "UNI", "terms": ["UNI", "$UNI", "Uniswap"]},
    {"symbol": "APT", "terms": ["APT", "$APT", "Aptos"]},
    {"symbol": "ICP", "terms": ["ICP", "$ICP", "Internet Computer"]},
    {"symbol": "ETC", "terms": ["ETC", "$ETC", "Ethereum Classic", "以太经典"]},
    {"symbol": "XLM", "terms": ["XLM", "$XLM", "Stellar", "恒星币"]},
    {"symbol": "HBAR", "terms": ["HBAR", "$HBAR", "Hedera"]},
    {"symbol": "FIL", "terms": ["FIL", "$FIL", "Filecoin", "文件币"]},
    {"symbol": "ATOM", "terms": ["ATOM", "$ATOM", "Cosmos", "阿童木"]},
    {"symbol": "ARB", "terms": ["ARB", "$ARB", "Arbitrum"]},
    {"symbol": "OP", "terms": ["OP", "$OP", "Optimism"]},
    {"symbol": "VET", "terms": ["VET", "$VET", "VeChain", "唯链"]},
    {"symbol": "INJ", "terms": ["INJ", "$INJ", "Injective"]},
    {"symbol": "RENDER", "terms": ["RENDER", "$RENDER", "Render"]},
    {"symbol": "RNDR", "terms": ["RNDR", "$RNDR"]},
    {"symbol": "MNT", "terms": ["MNT", "$MNT", "Mantle"]},
    {"symbol": "IMX", "terms": ["IMX", "$IMX", "Immutable"]},
    {"symbol": "SUI", "terms": ["SUI", "$SUI", "Sui"]},
    {"symbol": "TAO", "terms": ["TAO", "$TAO", "Bittensor"]},
    {"symbol": "GRT", "terms": ["GRT", "$GRT", "The Graph"]},
    {"symbol": "AAVE", "terms": ["AAVE", "$AAVE", "Aave"]},
    {"symbol": "MKR", "terms": ["MKR", "$MKR", "Maker"]},
    {"symbol": "ALGO", "terms": ["ALGO", "$ALGO", "Algorand"]},
    {"symbol": "QNT", "terms": ["QNT", "$QNT", "Quant"]},
    {"symbol": "STX", "terms": ["STX", "$STX", "Stacks"]},
    {"symbol": "LDO", "terms": ["LDO", "$LDO", "Lido DAO", "Lido"]},
    {"symbol": "SEI", "terms": ["SEI", "$SEI", "Sei"]},
    {"symbol": "EGLD", "terms": ["EGLD", "$EGLD", "MultiversX", "Elrond"]},
    {"symbol": "FLOW", "terms": ["FLOW", "$FLOW", "Flow"]},
    {"symbol": "SAND", "terms": ["SAND", "$SAND", "The Sandbox", "Sandbox"]},
    {"symbol": "AXS", "terms": ["AXS", "$AXS", "Axie Infinity"]},
    {"symbol": "MANA", "terms": ["MANA", "$MANA", "Decentraland"]},
    {"symbol": "CHZ", "terms": ["CHZ", "$CHZ", "Chiliz"]},
    {"symbol": "APE", "terms": ["APE", "$APE", "ApeCoin"]},
    {"symbol": "FTM", "terms": ["FTM", "$FTM", "Fantom"]},
    {"symbol": "RUNE", "terms": ["RUNE", "$RUNE", "THORChain"]},
    {"symbol": "KAS", "terms": ["KAS", "$KAS", "Kaspa"]},
    {"symbol": "TIA", "terms": ["TIA", "$TIA", "Celestia"]},
    {"symbol": "PYTH", "terms": ["PYTH", "$PYTH", "Pyth Network"]},
    {"symbol": "JUP", "terms": ["JUP", "$JUP", "Jupiter"]},
    {"symbol": "JTO", "terms": ["JTO", "$JTO", "Jito"]},
    {"symbol": "WIF", "terms": ["WIF", "$WIF", "dogwifhat"]},
    {"symbol": "BONK", "terms": ["BONK", "$BONK", "Bonk"]},
    {"symbol": "PEPE", "terms": ["PEPE", "$PEPE", "Pepe"]},
    {"symbol": "FLOKI", "terms": ["FLOKI", "$FLOKI", "Floki"]},
    {"symbol": "WLD", "terms": ["WLD", "$WLD", "Worldcoin"]},
    {"symbol": "STRK", "terms": ["STRK", "$STRK", "Starknet"]},
    {"symbol": "ZK", "terms": ["ZK", "$ZK", "ZKsync"]},
    {"symbol": "ENA", "terms": ["ENA", "$ENA", "Ethena"]},
    {"symbol": "ETHFI", "terms": ["ETHFI", "$ETHFI", "Ether.fi", "EtherFi"]},
    {"symbol": "PENDLE", "terms": ["PENDLE", "$PENDLE", "Pendle"]},
    {"symbol": "ONDO", "terms": ["ONDO", "$ONDO", "Ondo"]},
    {"symbol": "JASMY", "terms": ["JASMY", "$JASMY", "JasmyCoin"]},
    {"symbol": "AR", "terms": ["AR", "$AR", "Arweave"]},
    {"symbol": "ENS", "terms": ["ENS", "$ENS", "Ethereum Name Service"]},
    {"symbol": "CRV", "terms": ["CRV", "$CRV", "Curve", "Curve DAO"]},
    {"symbol": "SNX", "terms": ["SNX", "$SNX", "Synthetix"]},
    {"symbol": "COMP", "terms": ["COMP", "$COMP", "Compound"]},
    {"symbol": "YFI", "terms": ["YFI", "$YFI", "yearn.finance", "Yearn"]},
    {"symbol": "SUSHI", "terms": ["SUSHI", "$SUSHI", "SushiSwap"]},
    {"symbol": "CAKE", "terms": ["CAKE", "$CAKE", "PancakeSwap"]},
    {"symbol": "1INCH", "terms": ["1INCH", "$1INCH", "1inch"]},
    {"symbol": "LRC", "terms": ["LRC", "$LRC", "Loopring"]},
    {"symbol": "ZRX", "terms": ["ZRX", "$ZRX", "0x"]},
    {"symbol": "DYDX", "terms": ["DYDX", "$DYDX", "dYdX"]},
    {"symbol": "GMX", "terms": ["GMX", "$GMX"]},
    {"symbol": "CVX", "terms": ["CVX", "$CVX", "Convex"]},
    {"symbol": "BAL", "terms": ["BAL", "$BAL", "Balancer"]},
    {"symbol": "FXS", "terms": ["FXS", "$FXS", "Frax Share"]},
    {"symbol": "FRAX", "terms": ["FRAX", "$FRAX", "Frax"]},
    {"symbol": "DAI", "terms": ["DAI", "$DAI", "Dai"]},
    {"symbol": "TUSD", "terms": ["TUSD", "$TUSD", "TrueUSD"]},
    {"symbol": "USDD", "terms": ["USDD", "$USDD"]},
    {"symbol": "FDUSD", "terms": ["FDUSD", "$FDUSD", "First Digital USD"]},
    {"symbol": "BUSD", "terms": ["BUSD", "$BUSD", "Binance USD"]},
    {"symbol": "USTC", "terms": ["USTC", "$USTC", "TerraClassicUSD"]},
    {"symbol": "LUNC", "terms": ["LUNC", "$LUNC", "Terra Classic"]},
    {"symbol": "LUNA", "terms": ["LUNA", "$LUNA", "Terra"]},
    {"symbol": "XMR", "terms": ["XMR", "$XMR", "Monero", "门罗币"]},
    {"symbol": "ZEC", "terms": ["ZEC", "$ZEC", "Zcash", "大零币"]},
    {"symbol": "DASH", "terms": ["DASH", "$DASH", "Dash", "达世币"]},
    {"symbol": "EOS", "terms": ["EOS", "$EOS", "柚子币"]},
    {"symbol": "IOTA", "terms": ["IOTA", "$IOTA"]},
    {"symbol": "XTZ", "terms": ["XTZ", "$XTZ", "Tezos"]},
    {"symbol": "KAVA", "terms": ["KAVA", "$KAVA"]},
    {"symbol": "MINA", "terms": ["MINA", "$MINA", "Mina"]},
    {"symbol": "ROSE", "terms": ["ROSE", "$ROSE", "Oasis"]},
    {"symbol": "CELO", "terms": ["CELO", "$CELO", "Celo"]},
    {"symbol": "KSM", "terms": ["KSM", "$KSM", "Kusama"]},
    {"symbol": "WAVES", "terms": ["WAVES", "$WAVES", "Waves"]},
    {"symbol": "ZIL", "terms": ["ZIL", "$ZIL", "Zilliqa"]},
    {"symbol": "ONE", "terms": ["ONE", "$ONE", "Harmony"]},
    {"symbol": "IOTX", "terms": ["IOTX", "$IOTX", "IoTeX"]},
    {"symbol": "HNT", "terms": ["HNT", "$HNT", "Helium"]},
    {"symbol": "GALA", "terms": ["GALA", "$GALA", "Gala"]},
    {"symbol": "ENJ", "terms": ["ENJ", "$ENJ", "Enjin"]},
    {"symbol": "GMT", "terms": ["GMT", "$GMT", "STEPN"]},
    {"symbol": "MASK", "terms": ["MASK", "$MASK", "Mask Network"]},
    {"symbol": "BLUR", "terms": ["BLUR", "$BLUR", "Blur"]},
    {"symbol": "MAGIC", "terms": ["MAGIC", "$MAGIC", "Treasure"]},
    {"symbol": "ILV", "terms": ["ILV", "$ILV", "Illuvium"]},
    {"symbol": "ORDI", "terms": ["ORDI", "$ORDI"]},
    {"symbol": "SATS", "terms": ["SATS", "$SATS", "1000SATS"]},
    {"symbol": "RATS", "terms": ["RATS", "$RATS"]},
    {"symbol": "BRC20", "terms": ["BRC20", "BRC-20"]},
    {"symbol": "MATIC", "terms": ["MATIC", "$MATIC", "马蹄"]},
    {"symbol": "POL", "terms": ["POL", "$POL", "Polygon", "Polygon Ecosystem Token"]},
    {"symbol": "HYPE", "terms": ["HYPE", "$HYPE", "Hyperliquid"]},
    {"symbol": "FET", "terms": ["FET", "$FET", "Fetch.ai", "Artificial Superintelligence Alliance"]},
    {"symbol": "AGIX", "terms": ["AGIX", "$AGIX", "SingularityNET"]},
    {"symbol": "OCEAN", "terms": ["OCEAN", "$OCEAN", "Ocean Protocol"]},
    {"symbol": "ARKM", "terms": ["ARKM", "$ARKM", "Arkham"]},
    {"symbol": "GNO", "terms": ["GNO", "$GNO", "Gnosis"]},
    {"symbol": "W", "terms": ["W", "$W", "Wormhole"]},
    {"symbol": "WOO", "terms": ["WOO", "$WOO", "WOO Network"]},
    {"symbol": "BAT", "terms": ["BAT", "$BAT", "Basic Attention Token"]},
    {"symbol": "NEXO", "terms": ["NEXO", "$NEXO", "Nexo"]},
    {"symbol": "OKB", "terms": ["OKB", "$OKB", "OKB"]},
    {"symbol": "CRO", "terms": ["CRO", "$CRO", "Cronos"]},
    {"symbol": "GT", "terms": ["GT", "$GT", "GateToken"]},
    {"symbol": "BGB", "terms": ["BGB", "$BGB", "Bitget Token"]},
    {"symbol": "KCS", "terms": ["KCS", "$KCS", "KuCoin Token"]},
    {"symbol": "HT", "terms": ["HT", "$HT", "Huobi Token"]},
    {"symbol": "LEO", "terms": ["LEO", "$LEO", "UNUS SED LEO"]},
    {"symbol": "FTT", "terms": ["FTT", "$FTT", "FTX Token"]},
]

EXCHANGES = [
    {"name": "Binance", "terms": ["Binance", "币安"]},
    {"name": "OKX", "terms": ["OKX", "OKEx", "欧易"]},
    {"name": "Coinbase", "terms": ["Coinbase"]},
    {"name": "Bybit", "terms": ["Bybit"]},
    {"name": "Kraken", "terms": ["Kraken"]},
    {"name": "Huobi", "terms": ["Huobi", "HTX", "火币"]},
    {"name": "Gate", "terms": ["Gate", "Gate.io", "芝麻开门"]},
    {"name": "Bitget", "terms": ["Bitget"]},
    {"name": "KuCoin", "terms": ["KuCoin", "库币"]},
    {"name": "MEXC", "terms": ["MEXC", "抹茶"]},
    {"name": "Crypto.com", "terms": ["Crypto.com"]},
    {"name": "Bitfinex", "terms": ["Bitfinex"]},
    {"name": "Bitstamp", "terms": ["Bitstamp"]},
    {"name": "Gemini", "terms": ["Gemini"]},
    {"name": "Bithumb", "terms": ["Bithumb"]},
    {"name": "Upbit", "terms": ["Upbit"]},
    {"name": "Deribit", "terms": ["Deribit"]},
    {"name": "BitMEX", "terms": ["BitMEX"]},
    {"name": "CoinEx", "terms": ["CoinEx"]},
    {"name": "Poloniex", "terms": ["Poloniex"]},
    {"name": "Bittrex", "terms": ["Bittrex"]},
    {"name": "Binance.US", "terms": ["Binance.US", "币安美国"]},
    {"name": "Hyperliquid", "terms": ["Hyperliquid"]},
    {"name": "dYdX", "terms": ["dYdX"]},
    {"name": "Uniswap", "terms": ["Uniswap"]},
    {"name": "PancakeSwap", "terms": ["PancakeSwap"]},
    {"name": "Curve", "terms": ["Curve"]},
    {"name": "SushiSwap", "terms": ["SushiSwap"]},
]
CHAINS = ["Ethereum", "BSC", "BNB Chain", "Solana", "Bitcoin", "Tron", "Polygon", "Arbitrum", "Optimism"]
KEYWORD_REFERENCE_MAP = {
    "hack": "security_event",
    "exploit": "security_event",
    "attack": "security_event",
    "rug": "fraud_or_exit_risk",
    "depeg": "stablecoin_risk",
    "liquidation": "market_liquidation",
    "whale": "large_transfer_reference",
    "stolen": "asset_loss_reference",
    "drain": "asset_outflow_reference",
    "freeze": "operational_or_legal_reference",
    "insolvency": "solvency_reference",
    "漏洞": "security_event",
    "攻击": "security_event",
    "被盗": "asset_loss_reference",
    "跑路": "fraud_or_exit_risk",
    "诈骗": "fraud_reference",
    "脱锚": "stablecoin_risk",
    "爆仓": "market_liquidation",
    "清算": "market_liquidation",
    "巨鲸": "large_transfer_reference",
    "大额转账": "large_transfer_reference",
    "暂停提现": "exchange_operation_reference",
    "无法提现": "exchange_operation_reference",
    "宕机": "exchange_operation_reference",
    "监管调查": "regulatory_reference",
    "储备不足": "solvency_reference",
    "暴跌": "market_volatility_reference",
    "量子计算": "potential_infrastructure_security_risk",
}

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


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _is_ascii_token_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")


def _term_in_text(text: str, lowered_text: str, term: str) -> bool:
    if not term:
        return False
    if _has_cjk(term):
        return term in text

    lowered_term = term.lower()
    start = 0
    while True:
        index = lowered_text.find(lowered_term, start)
        if index < 0:
            return False

        before = lowered_text[index - 1] if index > 0 else ""
        after_index = index + len(lowered_term)
        after = lowered_text[after_index] if after_index < len(lowered_text) else ""
        if not _is_ascii_token_char(before) and not _is_ascii_token_char(after):
            return True
        start = index + 1


def _extract_coin_symbols(text: str) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for coin in COINS:
        symbol = str(coin["symbol"])
        terms = [str(term) for term in coin["terms"]]
        if any(_term_in_text(text, lowered, term) for term in terms):
            matches.append(symbol)
    return _dedupe(matches)


def _extract_exchanges(text: str) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for exchange in EXCHANGES:
        name = str(exchange["name"])
        terms = [str(term) for term in exchange["terms"]]
        if any(_term_in_text(text, lowered, term) for term in terms):
            matches.append(name)
    return _dedupe(matches)


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


def _context_window(text: str, term: str, window: int = 42) -> str:
    lowered = text.lower()
    index = lowered.find(term.lower())
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(text), index + len(term) + window)
    return text[start:end]


def _extract_keyword_refs(text: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    lowered = text.lower()
    for term, ref_type in KEYWORD_REFERENCE_MAP.items():
        if term.lower() in lowered:
            refs.append(
                {
                    "term": term,
                    "type": ref_type,
                    "context": _context_window(text, term),
                }
            )
    return refs[:12]


def _detect_source_hint(text: str) -> str:
    match = re.search(r"据\s*([^，。,.]{2,32})\s*(?:报道|消息|披露|称)", text)
    if match:
        return match.group(1).strip()
    if "官方公告" in text or "公告称" in text:
        return "官方公告"
    if any(word in text.lower() for word in ["twitter", "x ", "telegram", "社群"]):
        return "社交媒体或社群消息"
    return ""


def prepare_chat_input(state: CryptoRiskState) -> CryptoRiskState:
    original_text = state.get("original_text", "")
    cleaned_text = " ".join(original_text.split())

    wallet_addresses = re.findall(r"0x[a-fA-F0-9]{40}|T[A-Za-z0-9]{33}|bc1[a-zA-Z0-9]{25,62}", cleaned_text)
    coins = _extract_coin_symbols(cleaned_text)
    exchanges = _extract_exchanges(cleaned_text)
    chains = [name for name in CHAINS if name.lower() in cleaned_text.lower()]
    input_type = _detect_input_type(cleaned_text)

    entities = {
        "projects": [],
        "tokens": coins,
        "coins": coins,
        "exchanges": _dedupe(exchanges),
        "wallet_addresses": _dedupe(wallet_addresses),
        "chains": _dedupe(chains),
    }

    raw_outputs = state.get("raw_agent_outputs", {})
    keyword_refs = _extract_keyword_refs(cleaned_text)
    source_hint = _detect_source_hint(cleaned_text)
    raw_outputs["input_tool"] = {
        "input_type": input_type,
        "entities": entities,
        "keyword_refs": keyword_refs,
        "source_hint": source_hint,
    }
    parsed_input = {
        "raw_text": original_text,
        "cleaned_text": cleaned_text,
        "input_type": input_type,
        "entities": entities,
        "keyword_refs": keyword_refs,
        "source_hint": source_hint,
    }

    return {
        **state,
        "raw_text": original_text,
        "cleaned_text": cleaned_text,
        "input_type": input_type,
        "entities": entities,
        "keyword_refs": keyword_refs,
        "source_hint": source_hint,
        "parsed_input": parsed_input,
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
