"""
TracePilot Web API Package
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskCreateRequest(BaseModel):
    dapp_name: str


class TxReviewRequest(BaseModel):
    tx_hash: str
    chain: str = "ethereum"
    tx_hashes: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)


class TxDetectRequest(BaseModel):
    tx_hashes: List[str] = Field(default_factory=list, min_length=1, max_length=50)
    chain: str = "ethereum"
    modules: List[str] = Field(default_factory=list)


class TxReviewEvidence(BaseModel):
    type: str
    title: str
    content: str
    source: str


class TxReviewSignal(BaseModel):
    id: str
    name: str
    level: str
    summary: str
    evidence: str
    confidence: str = "medium"


class TxReviewResponse(BaseModel):
    tx_hash: str
    chain: str
    risk_level: str
    tx_type: str
    summary: str
    signals: List[str] = Field(default_factory=list)
    signal_details: List[TxReviewSignal] = Field(default_factory=list)
    evidence: List[TxReviewEvidence] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    live_observation_status: str = "not_started"
    matched_cases: List[Dict[str, Any]] = Field(default_factory=list)
    recommend_deep_analysis: bool = False
    deep_analysis_ready: bool = False


class TxDetectItem(BaseModel):
    tx_hash: str
    risk_level: str
    classification: str
    summary: str
    signals: List[str] = Field(default_factory=list)
    signal_details: List[TxReviewSignal] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    matched_cases: List[Dict[str, Any]] = Field(default_factory=list)
    live_observation_status: str = "not_started"


class TxDetectResponse(BaseModel):
    chain: str
    input_count: int
    analyzed_count: int
    risk_level: str
    summary: str
    modules: List[str] = Field(default_factory=list)
    recommended_tx_hashes: List[str] = Field(default_factory=list)
    attack_candidates: List[TxDetectItem] = Field(default_factory=list)
    auxiliary_candidates: List[TxDetectItem] = Field(default_factory=list)
    unrelated_candidates: List[TxDetectItem] = Field(default_factory=list)
    invalid_hashes: List[str] = Field(default_factory=list)
    deep_analysis_ready: bool = False


class AssistantMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    scope: str = Field(default="general", pattern="^(general|tx_review|task|knowledge)$")
    question: str = Field(min_length=1, max_length=2000)
    task_id: Optional[str] = None
    tx_hash: Optional[str] = None
    chain: str = "ethereum"
    history: List[AssistantMessage] = Field(default_factory=list, max_length=8)


class AssistantSource(BaseModel):
    type: str
    title: str
    source: str
    content: Optional[str] = None


class AssistantChatResponse(BaseModel):
    answer: str
    scope: str
    model: str
    sources: List[AssistantSource] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)
    used_fallback: bool = False


class DappReference(BaseModel):
    time: Optional[str] = None
    link: Optional[str] = None


class DappCatalogItem(BaseModel):
    name: str
    cause: Optional[str] = None
    platform: Optional[str] = None
    time: Optional[str] = None
    root_cause: Optional[str] = None
    report: Optional[str] = None
    detection: Optional[DappReference] = None
    disclosure: Optional[DappReference] = None
    report_link: Optional[str] = None
    transaction_hash: List[str] = Field(default_factory=list)
    transaction_count: int = 0
    raw_file: str
    processed_file: Optional[str] = None
    has_processed_analysis: bool = False
    demo_ready: bool = False


class DappCatalogResponse(BaseModel):
    total: int
    demo_ready_count: int
    items: List[DappCatalogItem] = Field(default_factory=list)


class TaskResponse(BaseModel):
    task_id: str
    dapp_name: str
    status: TaskStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    duration: Optional[float] = None  # 耗时（秒）
    final_report: Optional[str] = None # 最终生成的 Markdown 报告内容
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    archived: bool = False

class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"

class MsgType(str, Enum):
    TEXT = "text"          # 纯文本
    MARKDOWN = "markdown"  # 格式化内容
    TOOL_CALL = "tool"     # 工具调用
    RESULT = "result"      # 最终结果

# class LogMessage(BaseModel):
#     agent: str
#     level: LogLevel
#     message_type: MsgType
#     message: str
#     is_truncated: bool = False
#     timestamp: Optional[str] = None
class LogMessage(BaseModel):
    agent: str
    level: LogLevel
    message_type: MsgType
    message: str
    is_truncated: bool = False
    timestamp: Optional[str] = None
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
