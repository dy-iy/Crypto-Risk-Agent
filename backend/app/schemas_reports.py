from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ReportDisposition = Literal["pending", "verified", "ignored", "monitoring", "reviewed"]


class AnalysisReportPayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=300)
    created_at: str = Field(..., min_length=1, max_length=64)
    input: str = Field(..., min_length=1)
    report: dict[str, object] = Field(default_factory=dict)
    disposition: ReportDisposition = "pending"
    disposition_note: str = Field(default="", max_length=1000)


class AnalysisReportItem(AnalysisReportPayload):
    user_id: str
    updated_at: str


class AnalysisReportDispositionUpdate(BaseModel):
    disposition: ReportDisposition
    disposition_note: str = Field(default="", max_length=1000)
