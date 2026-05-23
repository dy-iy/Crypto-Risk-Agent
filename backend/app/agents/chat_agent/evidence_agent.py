from app.llm import call_llm_json
from app.prompts.evidence_prompt import build_evidence_prompt
from app.state import CryptoRiskState


def _fallback_evidence(text: str, categories: list[str], signals: list[str]) -> list[dict[str, str]]:
    if not categories:
        return []

    snippet = text[:180]
    evidence: list[dict[str, str]] = []
    for index, category in enumerate(categories):
        signal = signals[index] if index < len(signals) else "文本中出现风险相关描述"
        evidence.append(
            {
                "risk_category": category,
                "evidence_text": snippet,
                "explanation": signal,
            }
        )
    return evidence


def evidence_agent(state: CryptoRiskState) -> CryptoRiskState:
    cleaned_text = state.get("cleaned_text", "")
    categories = state.get("risk_categories", [])
    prompt = build_evidence_prompt(cleaned_text, categories)
    llm_result = call_llm_json(prompt)

    evidence = llm_result.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    normalized = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "risk_category": str(item.get("risk_category", "")),
                "evidence_text": str(item.get("evidence_text", "")),
                "explanation": str(item.get("explanation", "")),
            }
        )

    if not normalized:
        normalized = _fallback_evidence(cleaned_text, categories, state.get("risk_signals", []))

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["evidence_agent"] = llm_result

    return {
        **state,
        "evidence": normalized,
        "raw_agent_outputs": raw_outputs,
    }
