from app.agents.chat_agent.score_agent import (
    _event_score_floor,
    _has_broad_user_impact,
    _has_confirmed_attack,
    _has_exchange_withdrawal_halt,
    _major_confirmed_security_factors,
    risk_level_from_score,
)
from app.state import CryptoRiskState


def _clamp(value: object, default: int = 0) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))


def _confidence_after_uncertainty(state: CryptoRiskState, confidence_score: int) -> int:
    missing = state.get("missing_information", []) or state.get("missing_info", [])
    overclaiming = state.get("overclaiming_risks", [])
    if missing or overclaiming:
        return min(confidence_score, 75)
    return confidence_score


def risk_calibration_agent(state: CryptoRiskState) -> CryptoRiskState:
    text = state.get("raw_text", state.get("cleaned_text", ""))
    original_score = _clamp(state.get("final_risk_score", state.get("risk_score", 0)))
    next_score = original_score
    severity_score = _clamp(state.get("severity_score"), next_score)
    confidence_score = _clamp(state.get("confidence_score"), 50)
    urgency_score = _clamp(state.get("urgency_score"), next_score)
    contagion_score = _clamp(state.get("contagion_score"), 30)
    rules: list[str] = []

    floor = _event_score_floor(state)
    if floor and next_score < floor:
        rules.append(f"触发重大事件评分下限：final_risk_score 从 {next_score} 上调至 {floor}。")
        next_score = floor
    elif floor:
        rules.append(f"已满足重大事件评分下限 {floor}。")

    if _has_exchange_withdrawal_halt(text):
        severity_score = max(severity_score, 78)
        urgency_score = max(urgency_score, 80)
        if _has_broad_user_impact(text) and next_score < 70:
            rules.append("触发提现异常硬规则：暂停提现 + 大量无法提款反馈，评分不得低于 70。")
            next_score = 70
        missing_terms = ["未提供明确恢复时间", "未提供储备证明", "未提供储备或钱包状态证明", "未提供第三方验证"]
        if any(item in state.get("missing_information", []) or item in state.get("missing_info", []) for item in missing_terms):
            if next_score < 68:
                rules.append("触发提现异常缺失信息规则：缺少恢复时间/储备证明/第三方验证，不能判为低风险。")
                next_score = 68
        state_status = state.get("risk_status", "uncertain")
        if state_status in {"no_risk", "potential_risk", "uncertain"}:
            rules.append("提现暂停属于已发生的用户资产可得性风险，risk_status 校准为 confirmed_risk。")
            state = {**state, "risk_status": "confirmed_risk"}

    if _has_confirmed_attack(text):
        major_factors = _major_confirmed_security_factors(text)
        high_risk_laundering_event = (
            major_factors.get("large_exposure_over_50m")
            and major_factors.get("unauthorized_mint_or_forged_asset")
            and major_factors.get("exfiltration_or_laundering")
        )
        if high_risk_laundering_event and next_score < 85:
            rules.append("触发高危攻击硬规则：已发生攻击 + 大额资产异常 + 资金外流/跨链/兑换/Tornado Cash/mixer 清洗信号，risk_score 不得低于 85。")
            next_score = 85
        elif major_factors.get("large_loss_over_100m") and next_score < 80:
            rules.append("触发大额攻击硬规则：已确认攻击且损失超过 1 亿美元，评分不得低于 80。")
            next_score = 80
        elif (
            major_factors.get("large_exposure_over_50m")
            and major_factors.get("unauthorized_mint_or_forged_asset")
            and next_score < 80
        ):
            rules.append("触发未授权铸造硬规则：已确认攻击且伪造/铸造资产敞口超过 5000 万美元，评分不得低于 80。")
            next_score = 80
        if major_factors.get("actual_loss_usd"):
            severity_score = max(severity_score, 85 if major_factors.get("large_loss_over_100m") else 76)
            urgency_score = max(urgency_score, 78)
            if major_factors.get("exfiltration_or_laundering"):
                urgency_score = max(urgency_score, 82)
                contagion_score = max(contagion_score, 65)
            state = {**state, "risk_status": "confirmed_risk"}

    if state.get("evidence_quality") in {"weak", "none"} and severity_score >= 70:
        old_confidence = confidence_score
        confidence_score = min(confidence_score, 60)
        if old_confidence != confidence_score:
            rules.append("证据不足只降低 confidence_score，不直接降低 risk_score 或 severity_score。")
    confidence_score = _confidence_after_uncertainty(state, confidence_score)

    next_score = _clamp(next_score)
    risk_level = risk_level_from_score(next_score)
    score_reason = state.get("score_reason", "")
    if rules:
        score_reason = f"{score_reason} 校准：{'；'.join(rules)}".strip()

    score_factors = state.get("score_factors", {})
    if not isinstance(score_factors, dict):
        score_factors = {}
    score_factors = {
        **score_factors,
        "calibration_applied": bool(rules),
        "calibration_principles": [
            "risk_score 表示事件风险严重性。",
            "confidence_score 表示信息可信度。",
            "不确定性只能降低 confidence_score，不能直接降低 risk_score。",
            "不得因官方尚未确认、信息来源有限、仍在发展中而把高危攻击事件降为中风险。",
        ],
        "calibration_rules": rules,
        "severity_score": severity_score,
        "confidence_score": confidence_score,
        "urgency_score": urgency_score,
        "contagion_score": contagion_score,
    }
    calibrated_result = {
        "risk_score": next_score,
        "risk_level": risk_level,
        "score_reason": score_reason,
        "score_factors": score_factors,
        "calibration_rules": rules,
    }

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["risk_calibration_agent"] = calibrated_result
    return {
        **state,
        "risk_score": next_score,
        "final_risk_score": next_score,
        "severity_score": severity_score,
        "confidence_score": confidence_score,
        "urgency_score": urgency_score,
        "contagion_score": contagion_score,
        "risk_level": risk_level,
        "score_reason": score_reason,
        "score_factors": score_factors,
        "calibration_rules": rules,
        "calibrated_result": calibrated_result,
        "raw_agent_outputs": raw_outputs,
    }
