from typing import Any, Literal, TypedDict


RiskStatus = Literal[
    "no_risk",
    "potential_risk",
    "confirmed_risk",
    "resolved_risk",
    "uncertain",
    "systemic_risk",
]
Confidence = Literal["high", "medium", "low"]
EvidenceQuality = Literal["strong", "medium", "weak", "none"]


class ParsedInput(TypedDict, total=False):
    raw_text: str
    cleaned_text: str
    input_type: str
    entities: dict[str, list[str]]
    keyword_refs: list[dict[str, str]]
    source_hint: str


class EvidenceSignal(TypedDict, total=False):
    text: str
    source_type: str
    signal_type: str
    supports: str


class MergedRiskResult(TypedDict, total=False):
    scoring: dict[str, object]
    classification: dict[str, object]
    impact: dict[str, object]
    uncertainty: dict[str, object]


class CalibratedRiskResult(TypedDict, total=False):
    risk_score: int
    risk_level: str
    score_reason: str
    score_factors: dict[str, object]
    calibration_rules: list[str]


class CryptoRiskState(TypedDict, total=False):
    raw_text: str
    original_text: str
    cleaned_text: str
    input_type: str
    entities: dict[str, list[str]]
    keyword_refs: list[dict[str, str]]
    source_hint: str
    parsed_input: ParsedInput
    has_risk: bool
    risk_status: RiskStatus
    risk_summary: str
    risk_signals: list[str]
    non_risk_factors: list[str]
    triage_confidence: Confidence
    supporting_evidence: list[dict[str, str]]
    counter_evidence: list[dict[str, str]]
    missing_info: list[str]
    confirmed_facts: list[str]
    uncertainty_points: list[str]
    evidence_items: list[EvidenceSignal]
    evidence_quality: EvidenceQuality
    risk_categories: list[str]
    primary_category: str | None
    secondary_categories: list[str]
    classification_reason: str
    classification_confidence: Confidence
    evidence: list[dict[str, str]]
    risk_score: int
    severity_score: int
    confidence_score: int
    confidence_level: str
    urgency_score: int
    contagion_score: int
    final_risk_score: int
    risk_level: str
    score_reason: str
    score_factors: dict[str, Any]
    score_confidence: Confidence
    score_breakdown: dict[str, int]
    impact: list[dict[str, str]] | list[str]
    impact_scope: str
    impact_severity: str
    affected_entities: list[str]
    affected_assets: list[str]
    loss_estimate: str
    systemic_risk: str
    user_asset_risk: str
    verified_claims: list[str]
    unverified_claims: list[str]
    official_explanation: list[str]
    missing_information: list[str]
    overclaiming_risks: list[str]
    advice: list[str]
    priority: str
    action_type: str
    has_conflict: bool
    review_issues: list[str]
    revision_suggestions: list[str]
    structured_review_result: dict[str, object]
    merged_result: MergedRiskResult
    calibrated_result: CalibratedRiskResult
    calibration_rules: list[str]
    risk_explanation: str
    final_report: dict[str, object]
    raw_agent_outputs: dict[str, object]
