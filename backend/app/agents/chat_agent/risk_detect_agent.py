from app.llm import call_llm_json
from app.prompts.risk_detect_prompt import build_risk_detect_prompt
from app.state import CryptoRiskState


RISK_KEYWORDS = [
    "hack",
    "exploit",
    "attack",
    "rug",
    "depeg",
    "liquidation",
    "whale",
    "stolen",
    "drain",
    "freeze",
    "insolvency",
    "漏洞",
    "攻击",
    "被盗",
    "跑路",
    "诈骗",
    "脱锚",
    "爆仓",
    "清算",
    "巨鲸",
    "大额转账",
    "暂停提现",
    "无法提现",
    "宕机",
    "监管调查",
    "储备不足",
    "暴跌",
]


def _heuristic_signals(text: str) -> list[str]:
    lowered = text.lower()
    signals: list[str] = []
    for keyword in RISK_KEYWORDS:
        if keyword.lower() in lowered:
            signals.append(f"文本提到“{keyword}”相关风险信号")
    return signals[:8]


def risk_detect_agent(state: CryptoRiskState) -> CryptoRiskState:
    cleaned_text = state.get("cleaned_text", "")
    prompt = build_risk_detect_prompt(cleaned_text, state.get("entities", {}))
    llm_result = call_llm_json(prompt)

    heuristic_signals = _heuristic_signals(cleaned_text)
    llm_signals = llm_result.get("risk_signals", [])
    if not isinstance(llm_signals, list):
        llm_signals = []

    risk_signals = [str(signal) for signal in llm_signals] or heuristic_signals
    has_risk = bool(llm_result.get("has_risk", False)) or bool(heuristic_signals)

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["risk_detect_agent"] = llm_result

    return {
        **state,
        "has_risk": has_risk,
        "risk_signals": risk_signals,
        "raw_agent_outputs": raw_outputs,
    }
