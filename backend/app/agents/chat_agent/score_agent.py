from app.llm import call_llm_json
from app.prompts.score_prompt import build_contextual_score_prompt
from app.state import CryptoRiskState
import re


BREAKDOWN_KEYS = ["severity", "evidence_strength", "impact_scope", "urgency", "reversibility"]


def risk_level_from_score(score: int) -> str:
    if score <= 20:
        return "低风险"
    if score <= 40:
        return "轻微风险"
    if score <= 60:
        return "中风险"
    if score <= 80:
        return "高风险"
    return "极高风险"


def _clamp_score(value: object, default: int = 0) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))


STATUS_DEFAULT_SCORES = {
    "no_risk": 5,
    "potential_risk": 25,
    "uncertain": 30,
    "resolved_risk": 20,
    "confirmed_risk": 55,
    "systemic_risk": 82,
}
STATUS_SCORE_RANGES = {
    "no_risk": (0, 10),
    "potential_risk": (11, 35),
    "uncertain": (20, 45),
    "resolved_risk": (10, 30),
    "confirmed_risk": (40, 75),
    "systemic_risk": (75, 100),
}
CONFIDENCE_VALUES = {"high", "medium", "low"}
WITHDRAWAL_HALT_TERMS = ["暂停所有提现", "暂停提现", "停止提现", "提现暂停", "暂停提款", "无法提现", "无法提款"]
EXCHANGE_CONTEXT_TERMS = ["交易所", "exchange", "平台"]
USER_IMPACT_TERMS = ["大量无法提现", "大量无法提款", "用户反馈", "社群反馈", "社群出现大量", "无法提款反馈"]
RESOLVED_TERMS = ["已恢复", "恢复提现", "已修复", "已解决", "已缓解"]
CONFIRMED_ATTACK_TERMS = [
    "遭受攻击",
    "遭攻击",
    "攻击事件",
    "漏洞攻击",
    "漏洞利用",
    "exploit",
    "hack",
    "attacker",
    "攻击者",
    "投毒",
    "伪造消息",
    "被盗",
    "盗取",
]
HIGH_CONFIDENCE_ATTRIBUTION_TERMS = ["Lazarus", "朝鲜黑客", "黑客集团", "攻击者为", "归因"]
INFRASTRUCTURE_ATTACK_TERMS = ["RPC", "基础设施", "DVN", "验证网络", "签名与验证", "跨链", "预言机", "oracle"]
UNAUTHORIZED_MINT_TERMS = [
    "未授权铸造",
    "未经授权铸造",
    "攻击者铸造",
    "伪造",
    "增发",
    "铸造",
    "minted",
    "unauthorized mint",
    "forged",
]
EXFILTRATION_TERMS = [
    "Tornado Cash",
    "混币",
    "跨链",
    "桥接",
    "兑换为 ETH",
    "转入 Tornado",
    "提取资金",
    "作为抵押",
    "借出",
    "launder",
    "bridge",
    "swap",
]


def _has_exchange_withdrawal_halt(text: str) -> bool:
    lowered = text.lower()
    return any(term in text for term in WITHDRAWAL_HALT_TERMS) and any(term in text or term in lowered for term in EXCHANGE_CONTEXT_TERMS)


def _has_broad_user_impact(text: str) -> bool:
    return any(term in text for term in USER_IMPACT_TERMS)


def _is_resolved(text: str) -> bool:
    return any(term in text for term in RESOLVED_TERMS)


def _event_score_floor(state: CryptoRiskState) -> int:
    text = state.get("raw_text", state.get("cleaned_text", ""))
    if _has_exchange_withdrawal_halt(text) and not _is_resolved(text):
        return 75 if _has_broad_user_impact(text) or "暂停所有提现" in text else 68
    major_loss_floor = _major_confirmed_security_event_floor(text)
    if major_loss_floor:
        return major_loss_floor
    return 0


def _has_confirmed_attack(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in CONFIRMED_ATTACK_TERMS)


def _has_high_confidence_attribution(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in HIGH_CONFIDENCE_ATTRIBUTION_TERMS)


def _has_infrastructure_attack_path(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in INFRASTRUCTURE_ATTACK_TERMS)


def _has_unauthorized_mint(text: str) -> bool:
    lowered = text.lower()
    has_attack_context = _has_confirmed_attack(text) or any(
        term in text or term.lower() in lowered
        for term in ["攻击路径", "漏洞", "提取资金", "攻击者", "exploit"]
    )
    has_mint = any(term in text or term.lower() in lowered for term in UNAUTHORIZED_MINT_TERMS)
    return has_attack_context and has_mint


def _has_exfiltration_or_laundering(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in EXFILTRATION_TERMS)


def _extract_usd_loss(text: str) -> float:
    def normalize_amount(amount_text: str, unit: str) -> float:
        amount = float(amount_text)
        if unit == "亿":
            return amount * 100_000_000
        if unit == "万":
            return amount * 10_000
        return amount

    patterns = [
        r"(?:损失|被盗|盗取|转出|窃取)[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD)[^，。,.]{0,12}(?:损失|被盗|盗取|窃取)",
        r"(?:铸造|伪造|增发|提取|借出|兑换|转入|转出|跨链)[^0-9]{0,36}([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD)[^，。,.；;]{0,36}(?:铸造|伪造|增发|提取|借出|兑换|转入|转出|跨链)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        return normalize_amount(match.group(1), match.group(2) or "")

    if _has_unauthorized_mint(text) or (_has_confirmed_attack(text) and _has_exfiltration_or_laundering(text)):
        usd_values = [
            normalize_amount(match.group(1), match.group(2) or "")
            for match in re.finditer(
                r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD)",
                text,
                flags=re.IGNORECASE,
            )
        ]
        if usd_values:
            return max(usd_values)

    english_match = re.search(
        r"(?:loss|lost|stolen|drained)[^0-9]{0,18}([0-9]+(?:\.[0-9]+)?)\s*(million|billion)\s*(?:usd|dollars?)",
        text,
        flags=re.IGNORECASE,
    )
    if english_match:
        amount = float(english_match.group(1))
        unit = english_match.group(2).lower()
        return amount * (1_000_000_000 if unit == "billion" else 1_000_000)

    return 0


def _major_confirmed_security_event_floor(text: str) -> int:
    if not _has_confirmed_attack(text):
        return 0

    loss_usd = _extract_usd_loss(text)
    has_unauthorized_mint = _has_unauthorized_mint(text)
    has_exfiltration = _has_exfiltration_or_laundering(text)
    if loss_usd >= 100_000_000:
        return 82
    if loss_usd >= 50_000_000 and has_unauthorized_mint and has_exfiltration:
        return 85
    if loss_usd >= 50_000_000 and (has_unauthorized_mint or has_exfiltration):
        return 80
    if loss_usd >= 10_000_000:
        return 78
    if loss_usd >= 1_000_000:
        return 74 if has_exfiltration else 72

    if _has_high_confidence_attribution(text) and _has_infrastructure_attack_path(text):
        return 76
    return 0


def _major_confirmed_security_factors(text: str) -> dict[str, object]:
    loss_usd = _extract_usd_loss(text)
    return {
        "confirmed_attack": _has_confirmed_attack(text),
        "actual_loss_usd": int(loss_usd) if loss_usd else 0,
        "large_loss_over_100m": loss_usd >= 100_000_000,
        "large_exposure_over_50m": loss_usd >= 50_000_000,
        "unauthorized_mint_or_forged_asset": _has_unauthorized_mint(text),
        "exfiltration_or_laundering": _has_exfiltration_or_laundering(text),
        "high_confidence_attacker_attribution": _has_high_confidence_attribution(text),
        "infrastructure_attack_path": _has_infrastructure_attack_path(text),
    }


def _fallback_score(state: CryptoRiskState) -> tuple[int, dict[str, int]]:
    text = state.get("raw_text", state.get("original_text", ""))
    floor = _event_score_floor({"raw_text": text})
    status = "confirmed_risk" if floor or _has_confirmed_attack(text) else "uncertain"
    score = max(STATUS_DEFAULT_SCORES.get(status, 30), floor)
    evidence_quality = state.get("evidence_quality", "none")

    if evidence_quality == "strong":
        score += 8
    elif evidence_quality == "medium":
        score += 3
    elif evidence_quality == "none":
        score -= 10

    text = text.lower()
    if status in {"confirmed_risk", "systemic_risk"}:
        if any(word in text for word in ["损失", "被盗", "stolen", "drain", "攻击者", "铸造", "伪造", "tornado", "暂停提现", "无法提现", "脱锚"]):
            score += 8
    if any(word in text for word in ["已修复", "已恢复", "已缓解", "未发现", "没有实际", "讨论", "长期"]):
        score -= 8

    low, high = STATUS_SCORE_RANGES.get(status, (0, 100))
    score = max(low, min(high, _clamp_score(score)))
    score = max(score, floor)
    breakdown = {
        "severity": _clamp_score(score),
        "evidence_strength": {"strong": 85, "medium": 60, "weak": 35, "none": 5}.get(str(evidence_quality), 25),
        "impact_scope": _clamp_score(score + (10 if status == "systemic_risk" else 0)),
        "urgency": _clamp_score(score),
        "reversibility": _clamp_score(100 - score),
    }
    return score, breakdown


def score_agent(state: CryptoRiskState) -> CryptoRiskState:
    raw_text = state.get("original_text") or state.get("raw_text") or state.get("cleaned_text", "")
    evidence_result = {
        "supporting_evidence": state.get("supporting_evidence", []),
        "counter_evidence": state.get("counter_evidence", []),
        "missing_info": state.get("missing_info", []),
        "confirmed_facts": state.get("confirmed_facts", []),
        "risk_signals": state.get("risk_signals", []),
        "uncertainty_points": state.get("uncertainty_points", []),
        "evidence_items": state.get("evidence_items", []),
        "evidence_quality": state.get("evidence_quality", "none"),
    }
    prompt = build_contextual_score_prompt(
        raw_text,
        evidence_result,
    )
    llm_result = call_llm_json(prompt)

    score_input: CryptoRiskState = {
        "raw_text": raw_text,
        "evidence_quality": state.get("evidence_quality", "none"),
    }
    score, fallback_breakdown = _fallback_score(score_input)
    risk_score = _clamp_score(llm_result.get("final_risk_score", llm_result.get("risk_score")), score)
    status = "confirmed_risk" if _event_score_floor(score_input) or _has_confirmed_attack(raw_text) else "uncertain"
    low, high = STATUS_SCORE_RANGES.get(status, (0, 100))
    risk_score = max(low, min(high, risk_score))
    floor = _event_score_floor(score_input)
    if floor:
        risk_score = max(risk_score, floor)
    risk_level = risk_level_from_score(risk_score)

    breakdown_value = llm_result.get("score_breakdown", {})
    if not isinstance(breakdown_value, dict):
        breakdown_value = {}

    score_breakdown = {
        key: _clamp_score(breakdown_value.get(key), fallback_breakdown[key])
        for key in BREAKDOWN_KEYS
    }
    confidence = str(llm_result.get("confidence") or "low")
    if confidence not in CONFIDENCE_VALUES:
        confidence = "low"
    score_factors = llm_result.get("score_factors", {})
    if not isinstance(score_factors, dict):
        score_factors = {}
    floor = _event_score_floor(state)
    score_reason = str(llm_result.get("score_reason") or "")
    if floor:
        major_factors = _major_confirmed_security_factors(raw_text)
        score_factors = {
            **score_factors,
            "withdrawal_pause": _has_exchange_withdrawal_halt(raw_text),
            "broad_user_withdrawal_complaints": _has_broad_user_impact(raw_text),
            **major_factors,
            "score_floor_applied": floor,
        }
        confidence = "high"
        if major_factors["confirmed_attack"]:
            if major_factors.get("unauthorized_mint_or_forged_asset"):
                score_reason = (
                    "原文明确描述协议遭攻击，并出现未授权铸造/伪造资产及可量化美元风险敞口。"
                    "攻击者已通过抵押、借款、跨链、兑换或混币路径转移部分资产，说明事件严重性和处置紧迫性均较高，"
                    "因此按重大已确认链上安全事件校准评分。"
                )
            else:
                score_reason = (
                    "原文明确描述已发生攻击事件并造成实际资产损失。若同时存在大额损失、攻击者归因或基础设施攻击路径，"
                    "说明事件严重性、证据强度和处置紧迫性均较高，因此按重大已确认安全事件校准评分。"
                )
        else:
            score_reason = (
                "原文明确描述交易所暂停提现或提现功能大范围受阻，并伴随用户/社群无法提款反馈。"
                "该类事件直接影响用户资产可得性、平台运营稳定性和流动性信心，因此按高风险运营/兑付事件校准评分。"
            )

    severity_score = _clamp_score(llm_result.get("severity_score"), score_breakdown["severity"])
    confidence_score = _clamp_score(llm_result.get("confidence_score"), score_breakdown["evidence_strength"])
    urgency_score = _clamp_score(llm_result.get("urgency_score"), score_breakdown["urgency"])
    contagion_score = _clamp_score(llm_result.get("contagion_score"), score_breakdown["impact_scope"])
    if floor:
        severity_score = max(severity_score, min(100, floor + 5))
        urgency_score = max(urgency_score, min(100, floor))
        if floor >= 80:
            contagion_score = max(contagion_score, 65)
        confidence_score = max(confidence_score, 70 if state.get("evidence_quality") == "strong" else confidence_score)

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["score_agent"] = {
        "input_fields": ["original_text", "evidence_result"],
        "llm_result": llm_result,
    }

    return {
        **state,
        "risk_score": risk_score,
        "final_risk_score": risk_score,
        "severity_score": severity_score,
        "confidence_score": confidence_score,
        "urgency_score": urgency_score,
        "contagion_score": contagion_score,
        "risk_level": risk_level,
        "score_reason": score_reason,
        "score_factors": score_factors,
        "score_confidence": confidence,  # type: ignore[typeddict-item]
        "score_breakdown": score_breakdown,
        "raw_agent_outputs": raw_outputs,
    }
