from app.llm import call_llm_json
from app.prompts.evidence_prompt import build_contextual_evidence_prompt
from app.state import CryptoRiskState


EVIDENCE_QUALITIES = {"strong", "medium", "weak", "none"}
WITHDRAWAL_HALT_TERMS = ["暂停所有提现", "暂停提现", "停止提现", "提现暂停", "暂停提款", "无法提现", "无法提款"]
EXCHANGE_CONTEXT_TERMS = ["交易所", "exchange", "平台"]
USER_IMPACT_TERMS = ["大量无法提现", "大量无法提款", "用户反馈", "社群反馈", "社群出现大量", "无法提款反馈"]
CONFIRMED_ATTACK_TERMS = ["遭受攻击", "遭攻击", "攻击事件", "漏洞攻击", "漏洞利用", "攻击者", "投毒", "伪造消息", "被盗", "盗取", "exploit", "hack"]
LOSS_TERMS = ["损失", "被盗", "盗取", "窃取", "转出", "drained", "stolen", "lost"]


def _dict_list(value: object, keys: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {key: str(item.get(key, "")).strip() for key in keys}
        if any(normalized.values()):
            output.append(normalized)
    return output


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _evidence_signal_list(value: object) -> list[dict[str, str]]:
    return _dict_list(value, ["text", "source_type", "signal_type", "supports"])


def _context_window(text: str, term: str, window: int = 48) -> str:
    index = text.find(term)
    if index < 0:
        return ""
    start = max(0, index - window)
    end = min(len(text), index + len(term) + window)
    return text[start:end]


def _has_exchange_withdrawal_halt(text: str) -> bool:
    lowered = text.lower()
    return any(term in text for term in WITHDRAWAL_HALT_TERMS) and any(term in text or term in lowered for term in EXCHANGE_CONTEXT_TERMS)


def _calibrate_exchange_withdrawal_evidence(
    text: str,
    supporting_evidence: list[dict[str, str]],
    counter_evidence: list[dict[str, str]],
    missing_info: list[str],
    evidence_quality: str,
    confirmed_facts: list[str],
    risk_signals: list[str],
    uncertainty_points: list[str],
    evidence_items: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str], str, list[str], list[str], list[str], list[dict[str, str]]]:
    if not _has_exchange_withdrawal_halt(text):
        return supporting_evidence, counter_evidence, missing_info, evidence_quality, confirmed_facts, risk_signals, uncertainty_points, evidence_items

    next_supporting = list(supporting_evidence)
    next_facts = list(confirmed_facts)
    next_signals = list(risk_signals)
    next_uncertainty = list(uncertainty_points)
    next_items = list(evidence_items)
    for term in WITHDRAWAL_HALT_TERMS:
        context = _context_window(text, term)
        if context:
            next_supporting.append(
                {
                    "text": context,
                    "supports": "confirmed_risk",
                    "evidence_type": "withdrawal_pause",
                }
            )
            next_facts.append(context)
            next_signals.append("交易所提现功能暂停或大范围受阻")
            next_items.append(
                {
                    "text": context,
                    "source_type": "原文事实",
                    "signal_type": "withdrawal_pause",
                    "supports": "confirmed_risk",
                }
            )
            break

    if any(term in text for term in USER_IMPACT_TERMS):
        next_supporting.append(
            {
                "text": "社群出现大量无法提款反馈",
                "supports": "confirmed_risk",
                "evidence_type": "user_impact",
            }
        )
        next_signals.append("用户或社群出现无法提款反馈")
        next_items.append(
            {
                "text": "社群出现大量无法提款反馈",
                "source_type": "社群反馈",
                "signal_type": "user_impact",
                "supports": "confirmed_risk",
            }
        )

    next_counter = [
        item
        for item in counter_evidence
        if "不是已发生" not in item.get("meaning", "") and "不足以确认" not in item.get("meaning", "")
    ]
    next_missing = [item for item in missing_info if item not in {"没有具体攻击事件", "没有损失金额"}]
    for missing in ["未提供明确恢复时间", "未提供第三方验证", "未提供储备或钱包状态证明"]:
        if missing not in next_missing:
            next_missing.append(missing)
        if missing not in next_uncertainty:
            next_uncertainty.append(missing)
    return next_supporting, next_counter, next_missing, "strong", next_facts, next_signals, next_uncertainty, next_items


def _has_confirmed_attack_with_loss(text: str) -> bool:
    lowered = text.lower()
    has_attack = any(term in text or term.lower() in lowered for term in CONFIRMED_ATTACK_TERMS)
    has_loss = any(term in text or term.lower() in lowered for term in LOSS_TERMS)
    has_amount = any(unit in text for unit in ["美元", "美金", "USD", "亿", "万"])
    return has_attack and has_loss and has_amount


def _calibrate_confirmed_attack_evidence(
    text: str,
    supporting_evidence: list[dict[str, str]],
    counter_evidence: list[dict[str, str]],
    missing_info: list[str],
    evidence_quality: str,
    confirmed_facts: list[str],
    risk_signals: list[str],
    uncertainty_points: list[str],
    evidence_items: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str], str, list[str], list[str], list[str], list[dict[str, str]]]:
    if not _has_confirmed_attack_with_loss(text):
        return supporting_evidence, counter_evidence, missing_info, evidence_quality, confirmed_facts, risk_signals, uncertainty_points, evidence_items

    next_supporting = list(supporting_evidence)
    next_facts = list(confirmed_facts)
    next_signals = list(risk_signals)
    next_uncertainty = list(uncertainty_points)
    next_items = list(evidence_items)
    for term in CONFIRMED_ATTACK_TERMS:
        context = _context_window(text, term)
        if context:
            next_supporting.append(
                {
                    "text": context,
                    "supports": "confirmed_risk",
                    "evidence_type": "confirmed_attack",
                }
            )
            next_facts.append(context)
            next_signals.append("已确认攻击事件")
            next_items.append(
                {
                    "text": context,
                    "source_type": "原文事实",
                    "signal_type": "confirmed_attack",
                    "supports": "confirmed_risk",
                }
            )
            break
    for term in LOSS_TERMS:
        context = _context_window(text, term)
        if context:
            next_supporting.append(
                {
                    "text": context,
                    "supports": "confirmed_risk",
                    "evidence_type": "actual_loss",
                }
            )
            next_signals.append("存在实际资产损失")
            next_items.append(
                {
                    "text": context,
                    "source_type": "原文事实",
                    "signal_type": "actual_loss",
                    "supports": "confirmed_risk",
                }
            )
            break

    next_counter = [
        item
        for item in counter_evidence
        if "不是已发生" not in item.get("meaning", "") and "不足以确认" not in item.get("meaning", "")
    ]
    next_missing = [item for item in missing_info if item not in {"没有具体攻击事件", "没有损失金额"}]
    if "追回资金进展仍需跟踪" not in next_uncertainty:
        next_uncertainty.append("追回资金进展仍需跟踪")
    return next_supporting, next_counter, next_missing, "strong", next_facts, next_signals, next_uncertainty, next_items


def evidence_agent(state: CryptoRiskState) -> CryptoRiskState:
    triage_result = {
        "risk_status": state.get("risk_status", "uncertain"),
        "risk_summary": state.get("risk_summary", ""),
        "risk_signals": state.get("risk_signals", []),
        "non_risk_factors": state.get("non_risk_factors", []),
        "confidence": state.get("triage_confidence", "low"),
    }
    prompt = build_contextual_evidence_prompt(
        state.get("raw_text", state.get("original_text", "")),
        state.get("cleaned_text", ""),
        state.get("entities", {}),
        state.get("keyword_refs", []),
        triage_result,
    )
    llm_result = call_llm_json(prompt)

    supporting_evidence = _dict_list(llm_result.get("supporting_evidence"), ["text", "supports", "evidence_type"])
    counter_evidence = _dict_list(llm_result.get("counter_evidence"), ["text", "meaning"])
    missing_info = _string_list(llm_result.get("missing_info"))
    confirmed_facts = _string_list(llm_result.get("confirmed_facts"))
    extracted_risk_signals = _string_list(llm_result.get("risk_signals"))
    uncertainty_points = _string_list(llm_result.get("uncertainty_points"))
    evidence_items = _evidence_signal_list(llm_result.get("evidence_items"))
    evidence_quality = str(llm_result.get("evidence_quality") or "none")
    if evidence_quality not in EVIDENCE_QUALITIES:
        evidence_quality = "none" if not supporting_evidence else "weak"

    (
        supporting_evidence,
        counter_evidence,
        missing_info,
        evidence_quality,
        confirmed_facts,
        extracted_risk_signals,
        uncertainty_points,
        evidence_items,
    ) = _calibrate_exchange_withdrawal_evidence(
        state.get("raw_text", state.get("cleaned_text", "")),
        supporting_evidence,
        counter_evidence,
        missing_info,
        evidence_quality,
        confirmed_facts,
        extracted_risk_signals,
        uncertainty_points,
        evidence_items,
    )
    (
        supporting_evidence,
        counter_evidence,
        missing_info,
        evidence_quality,
        confirmed_facts,
        extracted_risk_signals,
        uncertainty_points,
        evidence_items,
    ) = _calibrate_confirmed_attack_evidence(
        state.get("raw_text", state.get("cleaned_text", "")),
        supporting_evidence,
        counter_evidence,
        missing_info,
        evidence_quality,
        confirmed_facts,
        extracted_risk_signals,
        uncertainty_points,
        evidence_items,
    )

    merged_risk_signals = list(dict.fromkeys([*state.get("risk_signals", []), *extracted_risk_signals]))

    compatibility_evidence = [
        {
            "risk_category": item.get("supports", ""),
            "evidence_text": item.get("text", ""),
            "explanation": item.get("evidence_type", ""),
        }
        for item in supporting_evidence
    ]

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["evidence_agent"] = llm_result

    return {
        **state,
        "supporting_evidence": supporting_evidence,
        "counter_evidence": counter_evidence,
        "missing_info": missing_info,
        "confirmed_facts": list(dict.fromkeys(confirmed_facts)),
        "risk_signals": merged_risk_signals,
        "uncertainty_points": list(dict.fromkeys(uncertainty_points)),
        "evidence_items": evidence_items,
        "evidence_quality": evidence_quality,  # type: ignore[typeddict-item]
        "evidence": compatibility_evidence,
        "raw_agent_outputs": raw_outputs,
    }
