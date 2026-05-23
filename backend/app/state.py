from typing import TypedDict


class CryptoRiskState(TypedDict, total=False):
    original_text: str
    cleaned_text: str
    input_type: str
    entities: dict[str, list[str]]
    has_risk: bool
    risk_signals: list[str]
    risk_categories: list[str]
    evidence: list[dict[str, str]]
    risk_score: int
    risk_level: str
    score_breakdown: dict[str, int]
    impact: list[str]
    advice: list[str]
    final_report: dict[str, object]
    raw_agent_outputs: dict[str, object]
