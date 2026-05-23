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


class RiskScoreBreakdown(BaseModel):
    severity: int = Field(0, ge=0, le=100)
    evidence_strength: int = Field(0, ge=0, le=100)
    impact_scope: int = Field(0, ge=0, le=100)
    urgency: int = Field(0, ge=0, le=100)
    reversibility: int = Field(0, ge=0, le=100)


class RiskReport(BaseModel):
    summary: str
    input_type: str = "unknown"
    has_risk: bool = False
    risk_score: int = Field(0, ge=0, le=100)
    risk_level: str = "低风险"
    risk_categories: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    entities: EntityExtraction = Field(default_factory=EntityExtraction)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    score_breakdown: RiskScoreBreakdown = Field(default_factory=RiskScoreBreakdown)
    impact: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    raw_agent_outputs: dict[str, object] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    status: str = "success"
    message: str = "分析完成"
    data: RiskReport
