from app.llm import call_llm_json
from app.prompts.explanation_prompt import build_explanation_prompt
from app.state import CryptoRiskState


def _fallback_explanation(state: CryptoRiskState) -> str:
    score = state.get("risk_score", 0)
    level = state.get("risk_level", "低风险")
    category = state.get("primary_category") or "综合风险"
    evidence_quality = state.get("evidence_quality", "none")
    return (
        f"该事件综合评分为 {score}/100，等级为「{level}」。主要类别为「{category}」。"
        f"当前证据质量为 {evidence_quality}，评分已区分事件严重性与证据置信度；"
        "缺失信息用于约束过度断言，不直接把已发生的高严重性事件降为低风险。"
    )


def risk_explanation_agent(state: CryptoRiskState) -> CryptoRiskState:
    llm_result = call_llm_json(
        build_explanation_prompt(
            state.get("raw_text", state.get("original_text", "")),
            dict(state.get("calibrated_result", {})),
            dict(state.get("merged_result", {})),
        )
    )
    explanation = str(llm_result.get("risk_explanation") or _fallback_explanation(state)).strip()
    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["risk_explanation_agent"] = llm_result
    return {
        **state,
        "risk_explanation": explanation,
        "raw_agent_outputs": raw_outputs,
    }
