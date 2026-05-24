from app.llm import call_llm_json
from app.prompts.explanation_prompt import build_explanation_prompt
from app.state import CryptoRiskState


def _fallback_explanation(state: CryptoRiskState) -> str:
    score = state.get("risk_score", 0)
    level = state.get("risk_level", "低风险")
    category = state.get("primary_category") or "综合风险"
    return f"该事件属于「{category}」，风险评分 {score}/100，等级为「{level}」。"


def _compact_explanation(text: str) -> str:
    blocked = [
        "右侧已生成",
        "可点击查看完整报告",
        "risk_score",
        "confidence_score",
        "风险严重性和信息置信度",
    ]
    cleaned = text.replace("\n", " ").strip()
    for term in blocked:
        if term in cleaned:
            cleaned = cleaned.split(term, 1)[0].strip(" ，。；;")
    first_sentence = cleaned.split("。", 1)[0].strip()
    if not first_sentence:
        first_sentence = cleaned[:80].strip()
    return f"{first_sentence[:80]}。" if first_sentence else ""


def risk_explanation_agent(state: CryptoRiskState) -> CryptoRiskState:
    llm_result = call_llm_json(
        build_explanation_prompt(
            state.get("raw_text", state.get("original_text", "")),
            dict(state.get("calibrated_result", {})),
            dict(state.get("merged_result", {})),
        )
    )
    explanation = _compact_explanation(str(llm_result.get("risk_explanation") or _fallback_explanation(state)))
    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["risk_explanation_agent"] = llm_result
    return {
        **state,
        "risk_explanation": explanation,
        "raw_agent_outputs": raw_outputs,
    }
