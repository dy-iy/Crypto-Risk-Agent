from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]


class UserWatchlist(BaseModel):
    id: str
    user_id: str = "demo_user"
    symbol: str
    base_asset: str
    is_holding: bool = False
    amount: float = Field(default=0, ge=0)
    avg_buy_price: float = Field(default=0, ge=0)
    alert_threshold: int = Field(default=70, ge=0, le=100)
    created_at: str
    updated_at: str


class UserWatchlistCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    is_holding: bool = False
    amount: float = Field(default=0, ge=0)
    avg_buy_price: float = Field(default=0, ge=0)
    alert_threshold: int = Field(default=70, ge=0, le=100)


class UserWatchlistUpdate(BaseModel):
    is_holding: bool | None = None
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
