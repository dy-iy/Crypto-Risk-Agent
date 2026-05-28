from __future__ import annotations

from app.agents.chat_agent.schemas import ScenarioId, Signal, SignalScanResult
from app.tools.risk_rule_labeler import score_all_risks


RULE_SCENARIO_MAP: dict[str, ScenarioId] = {
    "score_hack": "S1_ATTACK_EXPLOIT",
    "score_outage": "S2_EXCHANGE_ABNORMALITY",
    "score_stablecoin": "S3_STABLECOIN_RESERVE",
    "score_regulatory": "S5_REGULATORY_ENFORCEMENT",
    "score_liquidation": "S6_MARKET_LIQUIDATION",
    "score_volatility": "S6_MARKET_LIQUIDATION",
    "score_infra": "S4_INFRASTRUCTURE_FAILURE",
    "score_fraud": "S7_FRAUD_GOVERNANCE",
    "score_team": "S7_FRAUD_GOVERNANCE",
    "score_whale": "S8_WHALE_ONCHAIN_FLOW",
    "score_solvency": "S3_STABLECOIN_RESERVE",
    "score_macro": "S0_GENERAL_UNKNOWN",
}

SIGNAL_TYPES = {
    "score_hack": "attack_or_exploit_signal",
    "score_outage": "exchange_or_operations_signal",
    "score_stablecoin": "stablecoin_or_reserve_signal",
    "score_regulatory": "regulatory_signal",
    "score_liquidation": "liquidation_signal",
    "score_volatility": "market_volatility_signal",
    "score_infra": "infrastructure_signal",
    "score_fraud": "fraud_signal",
    "score_team": "governance_signal",
    "score_whale": "whale_onchain_signal",
    "score_solvency": "solvency_signal",
    "score_macro": "macro_signal",
}

NEGATIVE_PATTERNS = {
    "planned_maintenance": ["例行维护", "计划内维护", "系统升级", "常规维护"],
    "resolved_or_repaired": ["已恢复", "恢复正常", "已修复", "完成修复", "已解决"],
    "no_loss_or_no_impact": ["无资金损失", "未造成损失", "用户资金未受影响", "未受影响"],
    "discussion_only": ["讨论", "草案", "征求意见", "咨询", "监管框架", "呼吁", "建议", "观点", "分析称"],
    "security_research_only": ["安全研究", "漏洞披露", "审计报告", "漏洞赏金", "白帽"],
    "internal_transfer": ["内部调拨", "钱包归集", "冷钱包迁移", "官方钱包迁移"],
    "rumor_without_confirmation": ["传闻", "网传", "未经证实", "尚未发布公告", "没有链上", "缺少官方"],
    "normal_market_commentary": ["行情日报", "每日行情", "技术分析", "支撑位", "阻力位"],
    "positive_regulatory_clarity": ["法院驳回", "驳回", "放行", "批准", "豁免", "合规指引"],
    "ordinary_team_change": ["普通人事调整", "正常离职", "组织调整"],
}

CAP_RULES = [
    ("security_research_only", 45, "soft_cap", "安全研究或漏洞披露缺少已发生攻击证据"),
    ("planned_maintenance", 45, "soft_cap", "计划维护语境限制交易所异常高分"),
    ("resolved_or_repaired", 40, "soft_cap", "事件已恢复或修复"),
    ("discussion_only", 35, "soft_cap", "讨论、草案或观点类文本缺少实际风险事件"),
    ("internal_transfer", 30, "soft_cap", "内部归集或钱包迁移不能直接视作外部风险"),
    ("rumor_without_confirmation", 55, "soft_cap", "仅传闻或缺少官方/链上确认"),
    ("normal_market_commentary", 25, "soft_cap", "普通行情评论不能直接判为高风险事件"),
    ("positive_regulatory_clarity", 20, "soft_cap", "监管利好或指控被驳回"),
    ("ordinary_team_change", 35, "soft_cap", "普通团队变动不能直接判为高风险治理事件"),
]

NEGATIVE_SCENARIO_HINTS: dict[str, ScenarioId] = {
    "security_research_only": "S1_ATTACK_EXPLOIT",
    "planned_maintenance": "S2_EXCHANGE_ABNORMALITY",
    "rumor_without_confirmation": "S2_EXCHANGE_ABNORMALITY",
    "discussion_only": "S5_REGULATORY_ENFORCEMENT",
    "positive_regulatory_clarity": "S5_REGULATORY_ENFORCEMENT",
    "normal_market_commentary": "S6_MARKET_LIQUIDATION",
    "ordinary_team_change": "S7_FRAUD_GOVERNANCE",
}

EXTRA_POSITIVE_PATTERNS: dict[str, tuple[list[str], ScenarioId, float]] = {
    "phishing_or_fake_airdrop": (
        ["钓鱼网站", "钓鱼链接", "假空投", "虚假空投", "空投骗局", "冒充", "假代币", "诈骗网站"],
        "S7_FRAUD_GOVERNANCE",
        0.62,
    ),
    "rug_or_exit": (
        ["跑路", "Rug Pull", "rug", "卷款", "团队失联", "项目方失联", "流动性移除"],
        "S7_FRAUD_GOVERNANCE",
        0.72,
    ),
    "infra_failure": (
        ["停止出块", "网络中断", "主网暂停", "预言机异常", "跨链桥暂停", "RPC故障", "RPC 故障", "节点故障"],
        "S4_INFRASTRUCTURE_FAILURE",
        0.65,
    ),
    "whale_exchange_flow": (
        ["巨鲸", "大额转账", "转入交易所", "流入交易所", "未知钱包", "链上监测"],
        "S8_WHALE_ONCHAIN_FLOW",
        0.50,
    ),
}


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in text or term.lower() in lowered]


def _negative_signals(text: str) -> list[Signal]:
    signals: list[Signal] = []
    for signal_type, terms in NEGATIVE_PATTERNS.items():
        hits = _matched_terms(text, terms)
        if hits:
            scenario = NEGATIVE_SCENARIO_HINTS.get(signal_type)
            signals.append(
                Signal(
                    type=signal_type,
                    matched_terms=hits,
                    strength=-0.25,
                    scenario_hint=scenario,
                    reason=f"命中缓和/排除语义：{signal_type}",
                )
            )
    return signals


def _cap_signals(negative_signals: list[Signal]) -> list[Signal]:
    negative_types = {signal.type for signal in negative_signals}
    caps: list[Signal] = []
    for signal_type, score_cap, cap_type, reason in CAP_RULES:
        if signal_type in negative_types:
            caps.append(
                Signal(
                    type=signal_type,
                    strength=-0.4,
                    score_cap=score_cap,
                    cap_type=cap_type,  # type: ignore[arg-type]
                    reason=reason,
                )
            )
    return caps


def scan_fast_signals(text: str) -> SignalScanResult:
    cleaned = str(text or "")
    try:
        raw = score_all_risks(cleaned)
    except Exception as exc:
        return SignalScanResult(
            fast_exit_allowed=False,
            debug={"rule_labeler_error": str(exc)},
        )

    raw_scores = {
        key: float(value)
        for key, value in raw.items()
        if key.startswith("score_") and isinstance(value, (int, float))
    }
    scenario_scores: dict[ScenarioId, float] = {}
    positive: list[Signal] = []
    for rule_name, score in raw_scores.items():
        if score < 0.08:
            continue
        scenario = RULE_SCENARIO_MAP.get(rule_name, "S0_GENERAL_UNKNOWN")
        scenario_scores[scenario] = max(scenario_scores.get(scenario, 0.0), score)
        positive.append(
            Signal(
                type=SIGNAL_TYPES.get(rule_name, rule_name),
                strength=score,
                scenario_hint=scenario,
            )
        )

    negative = _negative_signals(cleaned)
    caps = _cap_signals(negative)
    for signal_type, (terms, scenario, strength) in EXTRA_POSITIVE_PATTERNS.items():
        hits = _matched_terms(cleaned, terms)
        if not hits:
            continue
        scenario_scores[scenario] = max(scenario_scores.get(scenario, 0.0), strength)
        positive.append(
            Signal(
                type=signal_type,
                matched_terms=hits,
                strength=strength,
                scenario_hint=scenario,
            )
        )
    for signal in negative:
        if signal.scenario_hint:
            scenario_scores[signal.scenario_hint] = max(scenario_scores.get(signal.scenario_hint, 0.0), 0.1)
    max_score = max(raw_scores.values(), default=0.0)
    high_signal_count = sum(1 for score in raw_scores.values() if score >= 0.4)
    suggested_top_k = 1 if max_score < 0.12 else 2
    if len([score for score in raw_scores.values() if score >= 0.25]) >= 3:
        suggested_top_k = 3
    if high_signal_count >= 3:
        suggested_top_k = 4

    fast_exit_allowed = max_score < 0.12 and not caps
    return SignalScanResult(
        positive_signals=positive,
        negative_signals=negative,
        cap_signals=caps,
        scenario_scores=scenario_scores,
        raw_rule_scores=raw_scores,
        suggested_top_k=suggested_top_k,
        fast_exit_allowed=fast_exit_allowed,
        debug={
            "legacy_risk": raw.get("risk"),
            "legacy_rule_label": raw.get("rule_label"),
            "legacy_primary_type": raw.get("rule_primary_type"),
            "legacy_rule_types": raw.get("rule_types"),
        },
    )
