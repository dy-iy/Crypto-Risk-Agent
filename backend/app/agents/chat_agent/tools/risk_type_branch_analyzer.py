from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.chat_agent.contracts import SCENARIO_FIELDS
from app.agents.chat_agent.schemas import (
    EvidenceContract,
    EvidenceExtractionResult,
    EvidenceFieldResult,
    RiskCaseInput,
    SignalScanResult,
)
from app.agents.chat_agent.tools.evidence_extractor import extract_evidence
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_SCENARIO_MAP, RISK_TYPE_ORDER
from app.llm import call_llm_json


MAX_EVIDENCE_ITEMS = 3
MAX_EVIDENCE_CHARS = 90


class _BranchFieldEvidence(BaseModel):
    field: str
    value: Any = None
    status: str = "missing"
    evidence_text: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class _BranchLLMResponse(BaseModel):
    risk_type: str
    established: bool = False
    severity_score: int = Field(0, ge=0, le=100)
    evidence_strength: int = Field(0, ge=0, le=100)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence_summary: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    field_evidence: list[_BranchFieldEvidence] = Field(default_factory=list)
    reasoning: str = ""


def _clamp(value: int | float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(float(value)))))


def _trim_text(value: object, max_chars: int = MAX_EVIDENCE_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def _hit_risk_types(signal_scan: SignalScanResult) -> list[str]:
    return [
        risk_type
        for risk_type in RISK_TYPE_ORDER
        if float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) > 0
    ]


def _build_branch_prompt(case_input: RiskCaseInput, signal_scan: SignalScanResult, risk_type: str) -> str:
    scenario = RISK_SCENARIO_MAP[risk_type]
    fields = SCENARIO_FIELDS[scenario]
    payload = {
        "risk_type": risk_type,
        "risk_name": RISK_NAME_MAP[risk_type],
        "scenario": scenario,
        "rule_score_100": int(round(float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) * 100)),
        "raw_text": case_input.raw_text,
        "entities": case_input.entities,
        "fields_to_check": fields,
    }
    return f"""
你是 CryptoRisk 的单风险类型证据审核 Agent。

你只负责一个 risk_type：{risk_type}（{RISK_NAME_MAP[risk_type]}）。
请理解整篇新闻，判断该 risk_type 是否真实成立，并提取支撑/反向证据。

硬性要求：
1. 证据必须是“理解后的概括”，不要完整摘抄原文字段或长句。
2. evidence_summary 最多 {MAX_EVIDENCE_ITEMS} 条，每条不超过 {MAX_EVIDENCE_CHARS} 个中文字符。
3. field_evidence.evidence_text 也必须是短概括，不要粘贴原文长句。
4. 如果只是传闻、预测、观点、例行维护、内部归集、已恢复、无损失，请降低 established、severity_score 和 evidence_strength。
5. 缺少关键事实时，missing_evidence 要指出缺什么；证据不足时 severity_score 不应高。
6. 不要给交易建议，不要输出 Markdown，只能输出 JSON。

JSON 格式：
{{
  "risk_type": "{risk_type}",
  "established": true,
  "severity_score": 65,
  "evidence_strength": 70,
  "confidence": 0.72,
  "evidence_summary": ["短证据概括1", "短证据概括2"],
  "missing_evidence": ["缺少官方确认"],
  "field_evidence": [
    {{
      "field": "{fields[0]}",
      "value": true,
      "status": "confirmed",
      "evidence_text": "短概括，不照抄原文",
      "confidence": 0.75
    }}
  ],
  "reasoning": "一句话说明该分支为什么成立或不成立"
}}

输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def _fallback_branch(case_input: RiskCaseInput, signal_scan: SignalScanResult, risk_type: str, error: str) -> dict[str, object]:
    rule_score = int(round(float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) * 100))
    return {
        "risk_type": risk_type,
        "risk_name": RISK_NAME_MAP[risk_type],
        "scenario": RISK_SCENARIO_MAP[risk_type],
        "rule_score": rule_score,
        "established": rule_score >= 45,
        "severity_score": min(rule_score, 45),
        "evidence_strength": 25,
        "confidence": 0.35,
        "branch_score": min(rule_score, 35),
        "evidence_summary": [_trim_text(f"规则命中{RISK_NAME_MAP[risk_type]}，但 LLM 证据审核不可用")],
        "missing_evidence": ["LLM 分支证据审核未完成"],
        "reasoning": error,
        "field_evidence": [],
        "source": "fallback",
    }


def _branch_score(rule_score: int, severity_score: int, evidence_strength: int, confidence: float, established: bool) -> int:
    base = max(rule_score, severity_score)
    if not established:
        return min(35, int(round(base * 0.45)))
    if evidence_strength >= 70:
        score = base
    elif evidence_strength >= 40:
        score = int(round(base * 0.82))
    else:
        score = int(round(base * 0.55))
    if confidence < 0.45:
        score = min(score, 40)
    if evidence_strength < 35:
        score = min(score, 38)
    return _clamp(score)


def _run_branch(case_input: RiskCaseInput, signal_scan: SignalScanResult, risk_type: str) -> dict[str, object]:
    raw_result = call_llm_json(_build_branch_prompt(case_input, signal_scan, risk_type), temperature=0.0)
    if raw_result.get("_llm_error"):
        return _fallback_branch(case_input, signal_scan, risk_type, str(raw_result["_llm_error"]))
    try:
        parsed = _BranchLLMResponse.model_validate(raw_result)
    except ValidationError as exc:
        return _fallback_branch(case_input, signal_scan, risk_type, str(exc))

    rule_score = int(round(float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) * 100))
    severity_score = _clamp(parsed.severity_score)
    evidence_strength = _clamp(parsed.evidence_strength)
    branch_score = _branch_score(
        rule_score=rule_score,
        severity_score=severity_score,
        evidence_strength=evidence_strength,
        confidence=parsed.confidence,
        established=parsed.established,
    )
    evidence_summary = [_trim_text(item) for item in parsed.evidence_summary[:MAX_EVIDENCE_ITEMS] if str(item).strip()]
    field_evidence = []
    valid_fields = set(SCENARIO_FIELDS[RISK_SCENARIO_MAP[risk_type]])
    for item in parsed.field_evidence:
        if item.field not in valid_fields:
            continue
        status = item.status if item.status in {"confirmed", "denied", "missing", "uncertain", "not_applicable"} else "missing"
        field_evidence.append(
            {
                "field": item.field,
                "value": item.value,
                "status": status,
                "evidence_text": _trim_text(item.evidence_text),
                "confidence": round(item.confidence, 2),
            }
        )

    return {
        "risk_type": risk_type,
        "risk_name": RISK_NAME_MAP[risk_type],
        "scenario": RISK_SCENARIO_MAP[risk_type],
        "rule_score": rule_score,
        "established": bool(parsed.established),
        "severity_score": severity_score,
        "evidence_strength": evidence_strength,
        "confidence": round(parsed.confidence, 2),
        "branch_score": branch_score,
        "evidence_summary": evidence_summary,
        "missing_evidence": [_trim_text(item, 60) for item in parsed.missing_evidence[:4]],
        "reasoning": _trim_text(parsed.reasoning, 120),
        "field_evidence": field_evidence,
        "source": "llm",
    }


def _branches_to_evidence(branches: list[dict[str, object]]) -> EvidenceExtractionResult:
    items: list[EvidenceFieldResult] = []
    missing_fields: list[str] = []
    llm_calls = 0
    fallback_count = 0
    for branch in branches:
        scenario = str(branch.get("scenario") or "")
        risk_type = str(branch.get("risk_type") or "")
        if branch.get("source") == "llm":
            llm_calls += 1
        else:
            fallback_count += 1
        for raw_item in branch.get("field_evidence", []):
            if not isinstance(raw_item, dict):
                continue
            field = str(raw_item.get("field") or "")
            items.append(
                EvidenceFieldResult(
                    scenario=scenario,  # type: ignore[arg-type]
                    field=field,
                    value=raw_item.get("value"),
                    status=str(raw_item.get("status") or "missing"),  # type: ignore[arg-type]
                    evidence_text=str(raw_item.get("evidence_text") or "") or None,
                    confidence=float(raw_item.get("confidence") or 0.0),
                )
            )
        for missing in branch.get("missing_evidence", []):
            missing_fields.append(f"{risk_type}:{missing}")
    return EvidenceExtractionResult(
        items=items,
        missing_fields=missing_fields,
        extraction_errors=[],
        raw_llm_output={"risk_type_branches": branches},
        extraction_mode="llm" if llm_calls else "heuristic_fallback",
        llm_call_count=llm_calls,
        fallback_count=fallback_count,
        json_parse_error_count=0,
    )


def analyze_risk_type_branches(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    contracts: list[EvidenceContract],
) -> tuple[SignalScanResult, EvidenceExtractionResult, list[dict[str, object]]]:
    risk_types = _hit_risk_types(signal_scan)
    if not risk_types:
        return signal_scan, extract_evidence(case_input, contracts), []

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(risk_types)))) as executor:
        branches = list(executor.map(lambda risk_type: _run_branch(case_input, signal_scan, risk_type), risk_types))

    evidence = _branches_to_evidence(branches)
    updated_debug = {**signal_scan.debug, "risk_type_branches": branches}
    updated_scan = signal_scan.model_copy(update={"debug": updated_debug})
    return updated_scan, evidence, branches
