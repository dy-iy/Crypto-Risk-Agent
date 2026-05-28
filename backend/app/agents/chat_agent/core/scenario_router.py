from __future__ import annotations

from app.agents.chat_agent.contracts import SCENARIO_FIELDS
from app.agents.chat_agent.schemas import ScenarioHypothesis, ScenarioId, SignalScanResult


HYPOTHESES: dict[ScenarioId, str] = {
    "S0_GENERAL_UNKNOWN": "文本存在弱风险信号或证据不足，需要判断是否无法归入具体风险场景。",
    "S1_ATTACK_EXPLOIT": "文本可能描述协议、合约、钱包或链上资产攻击事件。",
    "S2_EXCHANGE_ABNORMALITY": "文本可能描述交易所提现、充值、交易或资产可得性异常。",
    "S3_STABLECOIN_RESERVE": "文本可能描述稳定币脱锚、储备或赎回异常。",
    "S4_INFRASTRUCTURE_FAILURE": "文本可能描述链、节点、跨链桥、预言机或基础设施异常。",
    "S5_REGULATORY_ENFORCEMENT": "文本可能描述监管执法、诉讼、罚款、冻结或制裁。",
    "S6_MARKET_LIQUIDATION": "文本可能描述市场暴跌、清算、流动性压力或异常波动。",
    "S7_FRAUD_GOVERNANCE": "文本可能描述欺诈、跑路、团队异常或治理风险。",
    "S8_WHALE_ONCHAIN_FLOW": "文本可能描述巨鲸、大额转账或链上资金流向异常。",
}


def select_active_scenarios(signal_scan: SignalScanResult) -> list[ScenarioId]:
    ranked = sorted(signal_scan.scenario_scores.items(), key=lambda item: item[1], reverse=True)
    top_k = max(1, min(4, signal_scan.suggested_top_k))
    selected = [scenario for scenario, score in ranked if score >= 0.08][:top_k]
    if "S0_GENERAL_UNKNOWN" not in selected:
        selected.append("S0_GENERAL_UNKNOWN")
    return selected


def build_hypotheses(active_scenarios: list[ScenarioId]) -> list[ScenarioHypothesis]:
    return [
        ScenarioHypothesis(
            scenario=scenario,
            hypothesis=HYPOTHESES[scenario],
            priority=index + 1,
            required_fields=SCENARIO_FIELDS[scenario],
        )
        for index, scenario in enumerate(active_scenarios)
    ]


def route_scenarios(signal_scan: SignalScanResult) -> list[ScenarioHypothesis]:
    return build_hypotheses(select_active_scenarios(signal_scan))
