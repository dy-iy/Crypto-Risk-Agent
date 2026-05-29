from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User crypto risk text")


class EntityExtraction(BaseModel):
    projects: list[str] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list)
    exchanges: list[str] = Field(default_factory=list)
    wallet_addresses: list[str] = Field(default_factory=list)
    chains: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    risk_category: str
    evidence_text: str
    explanation: str


class SupportingEvidenceItem(BaseModel):
    text: str = ""
    supports: str = ""
    evidence_type: str = ""


class CounterEvidenceItem(BaseModel):
    text: str = ""
    meaning: str = ""


class ImpactItem(BaseModel):
    target: str = ""
    description: str = ""


class RiskScoreBreakdown(BaseModel):
    severity: int = Field(0, ge=0, le=100)
    evidence_strength: int = Field(0, ge=0, le=100)
    impact_scope: int = Field(0, ge=0, le=100)
    urgency: int = Field(0, ge=0, le=100)
    reversibility: int = Field(0, ge=0, le=100)


class EvidenceSignal(BaseModel):
    text: str = ""
    source_type: str = ""
    signal_type: str = ""
    supports: str = ""


class RiskReport(BaseModel):
    summary: str
    input_type: str = "unknown"
    has_risk: bool = False
    risk_status: str = "uncertain"
    risk_score: int = Field(0, ge=0, le=100)
    final_risk_score: int = Field(0, ge=0, le=100)
    risk_level: str = "低风险"
    confidence_level: str = "低"
    score_dimension_note: str = ""
    risk_categories: list[str] = Field(default_factory=list)
    primary_category: str | None = None
    secondary_categories: list[str] = Field(default_factory=list)
    classification_reason: str = ""
    classification_confidence: str = "low"
    risk_signals: list[str] = Field(default_factory=list)
    non_risk_factors: list[str] = Field(default_factory=list)
    triage_confidence: str = "low"
    entities: EntityExtraction = Field(default_factory=EntityExtraction)
    keyword_refs: list[dict[str, str]] = Field(default_factory=list)
    source_hint: str = ""
    supporting_evidence: list[SupportingEvidenceItem] = Field(default_factory=list)
    counter_evidence: list[CounterEvidenceItem] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    uncertainty_points: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceSignal] = Field(default_factory=list)
    evidence_quality: str = "none"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    severity_score: int = Field(0, ge=0, le=100)
    confidence_score: int = Field(0, ge=0, le=100)
    urgency_score: int = Field(0, ge=0, le=100)
    contagion_score: int = Field(0, ge=0, le=100)
    score_breakdown: RiskScoreBreakdown = Field(default_factory=RiskScoreBreakdown)
    score_reason: str = ""
    score_factors: dict[str, Any] = Field(default_factory=dict)
    score_confidence: str = "low"
    impact: list[str] = Field(default_factory=list)
    structured_impact: list[ImpactItem] = Field(default_factory=list)
    impact_scope: str = ""
    impact_severity: str = ""
    affected_entities: list[str] = Field(default_factory=list)
    affected_assets: list[str] = Field(default_factory=list)
    loss_estimate: str = ""
    systemic_risk: str = ""
    user_asset_risk: str = ""
    verified_claims: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    official_explanation: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    overclaiming_risks: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    priority: str = ""
    action_type: str = ""
    has_conflict: bool = False
    review_issues: list[str] = Field(default_factory=list)
    revision_suggestions: list[str] = Field(default_factory=list)
    structured_review_result: dict[str, object] = Field(default_factory=dict)
    calibration_rules: list[str] = Field(default_factory=list)
    risk_explanation: str = ""
    merged_result: dict[str, object] = Field(default_factory=dict)
    calibrated_result: dict[str, object] = Field(default_factory=dict)
    raw_agent_outputs: dict[str, object] = Field(default_factory=dict)
    chat_agent_result: dict[str, object] = Field(default_factory=dict)
    v6_result: dict[str, object] = Field(default_factory=dict)
    debug: dict[str, object] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    status: str = "success"
    message: str = "分析完成"
    data: RiskReport


class RiskAssistantRequest(BaseModel):
    question: str | None = Field(default=None, description="User question for risk assistant")
    selected_text: str | None = Field(default=None, description="Quoted page selection")
    user_question: str | None = Field(default=None, description="Question typed after quoting selected text")
    context: dict[str, object] = Field(default_factory=dict)


class RiskAssistantResponse(BaseModel):
    status: str = "success"
    message: str = "回答完成"
    answer: str
