from app.llm import call_llm_json
from app.prompts.uncertainty_prompt import build_uncertainty_prompt
from app.state import CryptoRiskState


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in terms)


def _calibrate_uncertainty(state: CryptoRiskState, result: dict[str, object]) -> dict[str, list[str]]:
    text = state.get("raw_text", state.get("cleaned_text", ""))
    verified = _string_list(result.get("verified_claims"))
    unverified = _string_list(result.get("unverified_claims"))
    official = _string_list(result.get("official_explanation"))
    missing = _string_list(result.get("missing_information"))
    overclaiming = _string_list(result.get("overclaiming_risks"))

    for fact in state.get("confirmed_facts", []):
        if fact not in verified:
            verified.append(fact)

    if _contains_any(text, ["官方称", "官方表示", "公告称", "宣布", "钱包系统维护", "系统维护"]):
        if "官方解释或公告口径需要继续核验执行进展" not in official:
            official.append("官方解释或公告口径需要继续核验执行进展")

    if _contains_any(text, ["社群反馈", "用户反馈", "大量无法提款", "大量无法提现"]):
        if "社群或用户反馈尚需与链上数据、客服响应和官方公告交叉验证" not in unverified:
            unverified.append("社群或用户反馈尚需与链上数据、客服响应和官方公告交叉验证")

    if _contains_any(text, ["暂停提现", "暂停所有提现", "无法提现", "无法提款"]):
        for item in ["未提供明确恢复时间", "未提供储备证明", "未提供第三方验证"]:
            if item not in missing:
                missing.append(item)
        for item in ["不能直接断言交易所跑路", "不能直接断言资不抵债"]:
            if item not in overclaiming:
                overclaiming.append(item)

    return {
        "verified_claims": list(dict.fromkeys(verified)),
        "unverified_claims": list(dict.fromkeys(unverified)),
        "official_explanation": list(dict.fromkeys(official)),
        "missing_information": list(dict.fromkeys(missing)),
        "overclaiming_risks": list(dict.fromkeys(overclaiming)),
    }


def uncertainty_agent(state: CryptoRiskState) -> CryptoRiskState:
    evidence_result = {
        "confirmed_facts": state.get("confirmed_facts", []),
        "risk_signals": state.get("risk_signals", []),
        "uncertainty_points": state.get("uncertainty_points", []),
        "supporting_evidence": state.get("supporting_evidence", []),
        "counter_evidence": state.get("counter_evidence", []),
        "missing_info": state.get("missing_info", []),
        "evidence_quality": state.get("evidence_quality", "none"),
    }
    llm_result = call_llm_json(
        build_uncertainty_prompt(
            state.get("raw_text", state.get("original_text", "")),
            dict(state.get("parsed_input", {})),
            evidence_result,
        )
    )
    calibrated = _calibrate_uncertainty(state, llm_result)

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["uncertainty_agent"] = llm_result
    return {
        **state,
        **calibrated,
        "raw_agent_outputs": raw_outputs,
    }
