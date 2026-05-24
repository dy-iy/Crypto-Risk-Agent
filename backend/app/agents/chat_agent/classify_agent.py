from app.llm import call_llm_json
from app.prompts.classify_prompt import RISK_CATEGORIES, build_contextual_classify_prompt
from app.state import CryptoRiskState


CONFIDENCE_VALUES = {"high", "medium", "low"}
WITHDRAWAL_HALT_TERMS = ["暂停所有提现", "暂停提现", "停止提现", "提现暂停", "暂停提款", "无法提现", "无法提款"]
EXCHANGE_CONTEXT_TERMS = ["交易所", "exchange", "平台"]
CONFIRMED_ATTACK_TERMS = ["遭受攻击", "遭攻击", "攻击事件", "漏洞攻击", "漏洞利用", "攻击者", "投毒", "伪造消息", "被盗", "盗取", "exploit", "hack"]
LOSS_TERMS = ["损失", "被盗", "盗取", "窃取", "转出", "drained", "stolen", "lost"]
UNAUTHORIZED_MINT_TERMS = ["未授权铸造", "未经授权铸造", "攻击者铸造", "伪造", "增发", "铸造", "minted", "unauthorized mint", "forged"]
EXFILTRATION_TERMS = ["Tornado Cash", "混币", "跨链", "桥接", "兑换", "提取资金", "作为抵押", "借出", "launder", "bridge", "swap"]
INFRASTRUCTURE_ATTACK_TERMS = ["RPC", "基础设施", "DVN", "验证网络", "签名与验证", "跨链", "预言机", "oracle"]


def _has_exchange_withdrawal_halt(text: str) -> bool:
    lowered = text.lower()
    return any(term in text for term in WITHDRAWAL_HALT_TERMS) and any(term in text or term in lowered for term in EXCHANGE_CONTEXT_TERMS)


def _has_confirmed_attack_with_loss(text: str) -> bool:
    lowered = text.lower()
    has_attack = any(term in text or term.lower() in lowered for term in CONFIRMED_ATTACK_TERMS)
    has_loss = any(term in text or term.lower() in lowered for term in LOSS_TERMS)
    has_unauthorized_mint = has_attack and any(term in text or term.lower() in lowered for term in UNAUTHORIZED_MINT_TERMS)
    has_exfiltration = any(term in text or term.lower() in lowered for term in EXFILTRATION_TERMS)
    has_amount = any(unit in text for unit in ["美元", "美金", "USD", "亿", "万"])
    return has_attack and (has_loss or has_unauthorized_mint or has_exfiltration) and has_amount


def _has_infrastructure_attack_path(text: str) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in INFRASTRUCTURE_ATTACK_TERMS)


def classify_agent(state: CryptoRiskState) -> CryptoRiskState:
    triage_result = {
        "risk_status": state.get("risk_status", "uncertain"),
        "risk_summary": state.get("risk_summary", ""),
        "risk_signals": state.get("risk_signals", []),
        "non_risk_factors": state.get("non_risk_factors", []),
        "confidence": state.get("triage_confidence", "low"),
    }
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
    prompt = build_contextual_classify_prompt(
        state.get("raw_text", state.get("original_text", "")),
        state.get("cleaned_text", ""),
        state.get("entities", {}),
        state.get("keyword_refs", []),
        triage_result,
        evidence_result,
    )
    llm_result = call_llm_json(prompt)

    primary_value = llm_result.get("primary_category")
    primary_category = str(primary_value) if primary_value else None
    if primary_category not in RISK_CATEGORIES and primary_category != "综合风险":
        primary_category = None

    secondary_value = llm_result.get("secondary_categories", [])
    if not isinstance(secondary_value, list):
        secondary_value = []
    secondary_categories = [str(category) for category in secondary_value if category in RISK_CATEGORIES]

    confidence = str(llm_result.get("classification_confidence") or "low")
    if confidence not in CONFIDENCE_VALUES:
        confidence = "low"

    if _has_exchange_withdrawal_halt(state.get("raw_text", state.get("cleaned_text", ""))):
        primary_category = "交易所与系统运维风险"
        if "偿付能力 / 储备 / 流动性风险" not in secondary_categories:
            secondary_categories.append("偿付能力 / 储备 / 流动性风险")
        confidence = "high"
    elif _has_confirmed_attack_with_loss(state.get("raw_text", state.get("cleaned_text", ""))):
        raw_text = state.get("raw_text", state.get("cleaned_text", ""))
        primary_category = "链上漏洞 / 攻击风险"
        if _has_infrastructure_attack_path(raw_text) and "基础设施 / 协议层异常风险" not in secondary_categories:
            secondary_categories.append("基础设施 / 协议层异常风险")
        confidence = "high"

    risk_categories = []
    if primary_category and primary_category != "综合风险":
        risk_categories.append(primary_category)
    risk_categories.extend(category for category in secondary_categories if category not in risk_categories)

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["classify_agent"] = llm_result

    return {
        **state,
        "primary_category": primary_category,
        "secondary_categories": secondary_categories,
        "classification_reason": str(llm_result.get("classification_reason") or ""),
        "classification_confidence": confidence,  # type: ignore[typeddict-item]
        "risk_categories": risk_categories,
        "raw_agent_outputs": raw_outputs,
    }
