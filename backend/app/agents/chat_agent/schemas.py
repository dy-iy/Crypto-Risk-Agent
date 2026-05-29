from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ScenarioId = Literal[
    "S0_GENERAL_UNKNOWN",
    "S1_ATTACK_EXPLOIT",
    "S2_EXCHANGE_ABNORMALITY",
    "S3_STABLECOIN_RESERVE",
    "S4_INFRASTRUCTURE_FAILURE",
    "S5_REGULATORY_ENFORCEMENT",
    "S6_MARKET_LIQUIDATION",
    "S7_FRAUD_GOVERNANCE",
    "S8_WHALE_ONCHAIN_FLOW",
]

EvidenceStatus = Literal["confirmed", "denied", "missing", "uncertain", "not_applicable"]
EvidenceExtractionMode = Literal["llm", "heuristic_fallback", "fast_exit"]
AnalysisPath = Literal["fast_exit", "deep_analysis"]
CapType = Literal["hard_cap", "soft_cap"]
RiskStatus = Literal[
    "low_risk",
    "potential_risk",
    "confirmed_risk",
    "insufficient_evidence",
    "resolved_or_mitigated",
    "false_positive_suppressed",
]
ValidationAction = Literal["cap_score", "raise_floor", "no_change"]


class RiskCaseInput(BaseModel):
    case_id: str
    raw_text: str
    title: str = ""
    content: str = ""
    source_url: str = ""
    source_name: str = ""
    published_at: str | None = None
    language: str = "zh"
    input_type: str = "unknown"
    entities: dict[str, list[str]] = Field(default_factory=dict)
    keyword_refs: list[dict[str, str]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Signal(BaseModel):
    type: str
    matched_terms: list[str] = Field(default_factory=list)
    strength: float = 0.0
    scenario_hint: ScenarioId | None = None
    score_cap: int | None = None
    cap_type: CapType | None = None
    reason: str = ""


class SignalScanResult(BaseModel):
    positive_signals: list[Signal] = Field(default_factory=list)
    negative_signals: list[Signal] = Field(default_factory=list)
    cap_signals: list[Signal] = Field(default_factory=list)
    scenario_scores: dict[ScenarioId, float] = Field(default_factory=dict)
    raw_rule_scores: dict[str, float] = Field(default_factory=dict)
    suggested_top_k: int = 2
    fast_exit_allowed: bool = False
    debug: dict[str, Any] = Field(default_factory=dict)


class OrchestrationDecision(BaseModel):
    path: AnalysisPath
    reason_codes: list[str] = Field(default_factory=list)
    needs_llm: bool = True
    needs_validation: bool = False
    initial_validation_hint: bool = False
    active_scenarios: list[ScenarioId] = Field(default_factory=list)


class EvidenceFieldResult(BaseModel):
    scenario: ScenarioId
    field: str
    value: Any = None
    status: EvidenceStatus = "missing"
    evidence_text: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("evidence_text")
    @classmethod
    def strip_evidence_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class EvidenceExtractionResult(BaseModel):
    items: list[EvidenceFieldResult] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    extraction_errors: list[str] = Field(default_factory=list)
    raw_llm_output: dict[str, Any] = Field(default_factory=dict)
    extraction_mode: EvidenceExtractionMode = "heuristic_fallback"
    llm_call_count: int = 0
    fallback_count: int = 0
    json_parse_error_count: int = 0

    def by_scenario(self, scenario: ScenarioId) -> dict[str, EvidenceFieldResult]:
        return {
            item.field: item
            for item in self.items
            if item.scenario == scenario
        }


class ValidationSuggestion(BaseModel):
    action: ValidationAction = "no_change"
    score_cap: int | None = None
    score_floor: int | None = None
    reason: str = ""
    answered_questions: dict[str, Any] = Field(default_factory=dict)


class DecisionResult(BaseModel):
    risk_score: int = Field(0, ge=0, le=100)
    pre_cap_score: int = Field(0, ge=0, le=100)
    risk_level: str = "低风险"
    risk_status: RiskStatus = "insufficient_evidence"
    primary_scenario: ScenarioId = "S0_GENERAL_UNKNOWN"
    secondary_scenarios: list[ScenarioId] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)
    score_caps_applied: list[str] = Field(default_factory=list)
    hard_caps_applied: list[str] = Field(default_factory=list)
    soft_caps_applied: list[str] = Field(default_factory=list)
    cap_conflicts: list[str] = Field(default_factory=list)
    score_floors_applied: list[str] = Field(default_factory=list)


class RiskCaseResult(BaseModel):
    case_input: RiskCaseInput
    signal_scan: SignalScanResult
    orchestration: OrchestrationDecision
    evidence: EvidenceExtractionResult = Field(default_factory=EvidenceExtractionResult)
    decision: DecisionResult
    validation: ValidationSuggestion | None = None
    report: dict[str, Any] = Field(default_factory=dict)
