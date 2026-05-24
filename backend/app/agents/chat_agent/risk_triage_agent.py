from app.llm import call_llm_json
from app.prompts.triage_prompt import build_triage_prompt
from app.state import CryptoRiskState


RISK_STATUSES = {"no_risk", "potential_risk", "confirmed_risk", "resolved_risk", "uncertain", "systemic_risk"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
WITHDRAWAL_HALT_TERMS = ["暂停所有提现", "暂停提现", "停止提现", "提现暂停", "暂停提款", "无法提现", "无法提款"]
EXCHANGE_CONTEXT_TERMS = ["交易所", "exchange", "平台"]
USER_IMPACT_TERMS = ["大量无法提现", "大量无法提款", "用户反馈", "社群反馈", "社群出现大量", "无法提款反馈"]
RESOLVED_TERMS = ["已恢复", "恢复提现", "已修复", "已解决", "已缓解"]
CONFIRMED_ATTACK_TERMS = ["遭受攻击", "遭攻击", "攻击事件", "漏洞攻击", "漏洞利用", "攻击者", "投毒", "伪造消息", "被盗", "盗取", "exploit", "hack"]
LOSS_TERMS = ["损失", "被盗", "盗取", "窃取", "转出", "drained", "stolen", "lost"]
HIGH_ATTRIBUTION_TERMS = ["Lazarus", "朝鲜黑客", "黑客集团"]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _fallback_status(state: CryptoRiskState) -> str:
    text = state.get("cleaned_text", "")
    lowered = text.lower()
    if any(term in text for term in ["未提到", "未发现", "没有实际", "暂无", "传闻", "疑似"]):
        return "uncertain"
    if any(term in text for term in ["已修复", "已恢复", "已缓解", "完成赔付", "漏洞修复"]):
        return "resolved_risk"
    if any(term in text for term in ["被盗", "攻击者", "资金池转出", "暂停提现", "无法提现", "脱锚"]):
        return "confirmed_risk"
    if any(term in lowered for term in ["potential", "可能", "或将", "长期", "讨论", "风险提示"]):
        return "potential_risk"
    return "uncertain" if state.get("keyword_refs") else "no_risk"


def _has_exchange_withdrawal_halt(text: str) -> bool:
    lowered = text.lower()
    has_withdrawal_issue = any(term in text for term in WITHDRAWAL_HALT_TERMS)
    has_exchange_context = any(term in text or term in lowered for term in EXCHANGE_CONTEXT_TERMS)
    return has_withdrawal_issue and has_exchange_context


def _has_broad_user_impact(text: str) -> bool:
    return any(term in text for term in USER_IMPACT_TERMS)


def _is_resolved(text: str) -> bool:
    return any(term in text for term in RESOLVED_TERMS)


def _has_confirmed_attack_with_loss(text: str) -> bool:
    lowered = text.lower()
    has_attack = any(term in text or term.lower() in lowered for term in CONFIRMED_ATTACK_TERMS)
    has_loss = any(term in text or term.lower() in lowered for term in LOSS_TERMS)
    has_amount = any(unit in text for unit in ["美元", "美金", "USD", "亿", "万"])
    return has_attack and has_loss and has_amount


def _has_high_confidence_attribution(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in HIGH_ATTRIBUTION_TERMS)


def _calibrate_status(state: CryptoRiskState, status: str, risk_signals: list[str], non_risk_factors: list[str]) -> tuple[str, list[str], list[str], str | None]:
    text = state.get("raw_text", state.get("cleaned_text", ""))
    if _has_exchange_withdrawal_halt(text):
        if _is_resolved(text):
            return "resolved_risk", risk_signals, non_risk_factors, "原文明确提到交易所提现异常但已恢复或已解决，校准为 resolved_risk。"

        calibrated_signals = list(risk_signals)
        if "交易所已暂停提现或出现无法提现反馈" not in calibrated_signals:
            calibrated_signals.append("交易所已暂停提现或出现无法提现反馈")
        if _has_broad_user_impact(text) and "社群或用户侧出现大范围无法提款反馈" not in calibrated_signals:
            calibrated_signals.append("社群或用户侧出现大范围无法提款反馈")

        calibrated_non_risk = [
            item
            for item in non_risk_factors
            if "未确认" not in item and "不足以确认" not in item and "未发生" not in item
        ]
        reason = "原文已明确描述交易所提现功能受限，这是已发生的交易所运营/流动性风险事件，不能因官方称维护而降为低风险。"
        return "confirmed_risk", calibrated_signals, calibrated_non_risk, reason

    if _has_confirmed_attack_with_loss(text):
        calibrated_signals = list(risk_signals)
        if "原文明确描述已发生攻击并造成资产损失" not in calibrated_signals:
            calibrated_signals.append("原文明确描述已发生攻击并造成资产损失")
        if _has_high_confidence_attribution(text) and "原文包含高置信度攻击者归因" not in calibrated_signals:
            calibrated_signals.append("原文包含高置信度攻击者归因")
        calibrated_non_risk = [
            item
            for item in non_risk_factors
            if "影响有限" not in item and "仅限" not in item
        ]
        reason = "原文明确描述攻击事件、实际资产损失和事件处置线索，属于已确认链上安全风险；影响范围有限只能限制扩散判断，不能否定事件严重性。"
        return "confirmed_risk", calibrated_signals, calibrated_non_risk, reason

    return status, risk_signals, non_risk_factors, None


def risk_triage_agent(state: CryptoRiskState) -> CryptoRiskState:
    prompt = build_triage_prompt(
        state.get("raw_text", state.get("original_text", "")),
        state.get("cleaned_text", ""),
        state.get("entities", {}),
        state.get("keyword_refs", []),
        state.get("source_hint", ""),
    )
    llm_result = call_llm_json(prompt)

    status = str(llm_result.get("risk_status") or "")
    if status not in RISK_STATUSES:
        status = _fallback_status(state)

    confidence = str(llm_result.get("confidence") or "low")
    if confidence not in CONFIDENCE_VALUES:
        confidence = "low"

    risk_signals = _string_list(llm_result.get("risk_signals"))
    non_risk_factors = _string_list(llm_result.get("non_risk_factors"))
    if not risk_signals and status in {"potential_risk", "confirmed_risk", "resolved_risk", "systemic_risk"}:
        risk_signals = [ref.get("context") or ref.get("term", "") for ref in state.get("keyword_refs", []) if ref.get("term")][:4]
    if not non_risk_factors and status in {"potential_risk", "uncertain", "no_risk"}:
        non_risk_factors = ["原文不足以确认已发生攻击、资金损失或系统性冲击。"]

    status, risk_signals, non_risk_factors, calibration_reason = _calibrate_status(state, status, risk_signals, non_risk_factors)
    if calibration_reason:
        confidence = "high"

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["risk_triage_agent"] = llm_result
    if calibration_reason:
        raw_outputs["risk_triage_calibration"] = {"reason": calibration_reason, "risk_status": status}

    has_risk = status not in {"no_risk"}
    return {
        **state,
        "has_risk": has_risk,
        "risk_status": status,  # type: ignore[typeddict-item]
        "risk_summary": calibration_reason or str(llm_result.get("risk_summary") or ""),
        "risk_signals": risk_signals,
        "non_risk_factors": non_risk_factors,
        "triage_confidence": confidence,  # type: ignore[typeddict-item]
        "raw_agent_outputs": raw_outputs,
    }
