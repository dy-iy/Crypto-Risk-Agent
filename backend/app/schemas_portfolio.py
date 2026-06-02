from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]
ExposureMode = Literal["bucket", "exact", "custom"]
ExposureBucket = Literal["none", "low", "medium", "high"]
ExposureSource = Literal["custom", "exact", "bucket", "unknown"]


class UserWatchlist(BaseModel):
    id: str
    user_id: str = "demo_user"
    symbol: str
    base_asset: str
    is_watched: bool = True
    is_holding: bool = False
    exposure_mode: ExposureMode = "bucket"
    exposure_bucket: ExposureBucket = "none"
    custom_exposure_pct: float | None = Field(default=None, ge=0, le=1)
    amount: float = Field(default=0, ge=0)
    avg_buy_price: float = Field(default=0, ge=0)
    alert_threshold: int = Field(default=70, ge=0, le=100)
    created_at: str
    updated_at: str


class UserWatchlistCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    is_watched: bool = True
    is_holding: bool = False
    exposure_mode: ExposureMode = "bucket"
    exposure_bucket: ExposureBucket = "none"
    custom_exposure_pct: float | None = Field(default=None, ge=0, le=1)
    amount: float = Field(default=0, ge=0)
    avg_buy_price: float = Field(default=0, ge=0)
    alert_threshold: int = Field(default=70, ge=0, le=100)


class UserWatchlistUpdate(BaseModel):
    is_watched: bool | None = None
    is_holding: bool | None = None
    exposure_mode: ExposureMode | None = None
    exposure_bucket: ExposureBucket | None = None
    custom_exposure_pct: float | None = Field(default=None, ge=0, le=1)
    amount: float | None = Field(default=None, ge=0)
    avg_buy_price: float | None = Field(default=None, ge=0)
    alert_threshold: int | None = Field(default=None, ge=0, le=100)


class MarketCandle(BaseModel):
    id: str
    symbol: str
    interval: str = "15m"
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "mock_fallback"
    created_at: str


class NewsCoinLink(BaseModel):
    id: str
    news_id: str
    symbol: str
    confidence: float = Field(default=0, ge=0, le=1)
    matched_reason: str = ""
    created_at: str


class EventAssetRelation(BaseModel):
    id: str
    event_id: str
    asset_symbol: str
    relation_score: float = Field(default=0, ge=0, le=1)
    relation_type: str = "direct_mention"
    direction: Literal["positive", "negative", "neutral"] = "neutral"
    base_asset_impact_score: int | None = Field(default=None, ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class PortfolioNewsItem(BaseModel):
    news_id: str
    title: str = ""
    content: str = ""
    published_at: str = ""
    risk_score: int = Field(default=0, ge=0, le=100)
    risk_level: str = ""
    risk_type: str = ""
    evidence: str = ""
    summary: str = ""
    source_url: str = ""
    matched_reason: str = ""
    confidence: float = Field(default=0, ge=0, le=1)


class PortfolioImpactEvent(BaseModel):
    eventId: str
    title: str = ""
    summary: str = ""
    publishedAt: str = ""
    eventRiskScore: int = Field(default=0, ge=0, le=100)
    assetRelationScore: float = Field(default=0, ge=0, le=1)
    userExposurePct: float = Field(default=0, ge=0, le=1)
    timeDecayFactor: float = Field(default=1, ge=0, le=1)
    urgencyScore: float = 1
    sourceTrustScore: float = 1
    confidenceScore: float = 1
    marketAnomalyFactor: float = 1
    userRiskPreferenceFactor: float = 1
    exposureSource: ExposureSource = "unknown"
    portfolioImpactScore: int = Field(default=0, ge=0, le=100)
    direction: Literal["positive", "negative", "neutral"] = "neutral"
    relationType: str = "direct_mention"
    riskType: str = ""
    sourceUrl: str = ""
    reasons: list[str] = Field(default_factory=list)


class PortfolioImpactAsset(BaseModel):
    assetSymbol: str
    holdingPct: float = Field(default=0, ge=0, le=1)
    exposureSource: ExposureSource = "unknown"
    marketValue: float = 0
    topEvents: list[PortfolioImpactEvent] = Field(default_factory=list)


class PortfolioImpactResponse(BaseModel):
    portfolioImpactScore: int = Field(default=0, ge=0, le=100)
    assets: list[PortfolioImpactAsset] = Field(default_factory=list)
    generatedAt: str
    windowDays: int = 30


class CoinRiskSnapshot(BaseModel):
    id: str
    user_id: str = "demo_user"
    symbol: str
    risk_score: int = Field(default=0, ge=0, le=100)
    risk_level: RiskLevel = "low"
    main_risk_types: list[str] = Field(default_factory=list)
    price_change_24h: float = 0
    related_news_count: int = 0
    high_risk_news_count: int = 0
    holding_impact: str = ""
    ai_summary: str = ""
    ai_advice: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    generated_at: str


class PortfolioWatchlistItem(UserWatchlist):
    current_price: float = 0
    price_change_24h: float = 0
    market_value: float = 0
    floating_pnl: float = 0
    floating_pnl_rate: float = 0
    risk_score: int = 0
    risk_level: RiskLevel = "low"
    ai_summary: str = ""


class PortfolioRefreshResponse(BaseModel):
    status: str = "success"
    message: str = "Portfolio risk data refreshed"
    updated_at: str
    success_symbols: int = 0
    related_news_count: int = 0
    risk_snapshots: int = 0
    symbols: list[str] = Field(default_factory=list)
    market_source: str = "mixed"


class PortfolioRefreshJob(BaseModel):
    job_id: str
    user_id: str = "demo_user"
    status: Literal["queued", "running", "success", "error"] = "queued"
    stage: str = "queued"
    message: str = "等待刷新"
    result: PortfolioRefreshResponse | None = None
    error: str = ""
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
