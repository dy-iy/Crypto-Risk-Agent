from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.agents.chat_agent.schemas import (
    EvidenceAtom,
    EvidenceGraphResult,
    RiskCaseInput,
    RiskHypothesis,
    ScenarioAssessment,
    Signal,
    SignalScanResult,
)
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_SCENARIO_MAP


COUNTER_SIGNAL_MEANINGS = {
    "planned_maintenance": "计划维护语境，降低交易所异常或跨链桥暂停的高危确定性。",
    "resolved_or_repaired": "事件已恢复或修复，风险处置状态会限制最终评分。",
    "no_loss_or_no_impact": "文本声明无损失或无影响，是高危结论的反向证据。",
    "discussion_only": "讨论、咨询、观点或草案类信息，不等同于已发生风险事件。",
    "security_research_only": "安全研究或漏洞披露缺少攻击落地证据。",
    "internal_transfer": "内部归集或钱包迁移不能直接推断为外部抛压。",
    "rumor_without_confirmation": "传闻或未确认信息，需要官方公告或链上证据补强。",
    "normal_market_commentary": "普通行情评论不等同于已发生清算或流动性冲击。",
    "positive_regulatory_clarity": "监管利好或澄清会压低执法风险。",
    "ordinary_team_change": "普通团队变动不能直接推断为跑路或治理危机。",
}


def _text(value: object, max_chars: int = 120) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _confidence(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _score(value: object) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def _affected_entities(case_input: RiskCaseInput) -> list[str]:
    entities: list[str] = []
    for values in case_input.entities.values():
        for value in values:
            item = str(value or "").strip()
            if item and item not in entities:
                entities.append(item)
    return entities[:10]


def build_evidence_graph(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    branches: list[dict[str, object]],
) -> EvidenceGraphResult:
    atoms: list[EvidenceAtom] = []
    counter_evidence: list[dict[str, str]] = []
    missing_by_scenario: dict[str, list[str]] = defaultdict(list)
    entity_refs = _affected_entities(case_input)

    def add_atom(
        scenario: str,
        risk_type: str,
        risk_name: str,
        polarity: str,
        field: str,
        text: str,
        source: str,
        confidence: float,
    ) -> str:
        atom_id = f"ev-{len(atoms) + 1:03d}"
        atoms.append(
            EvidenceAtom(
                id=atom_id,
                scenario=scenario,  # type: ignore[arg-type]
                risk_type=risk_type,
                risk_name=risk_name,
                polarity=polarity,  # type: ignore[arg-type]
                field=field,
                text=_text(text),
                source=source,
                confidence=_confidence(confidence),
                affected_entities=entity_refs,
            )
        )
        return atom_id

    hypotheses: list[RiskHypothesis] = []
    assessments: list[ScenarioAssessment] = []

    for branch in branches:
        risk_type = str(branch.get("risk_type") or "")
        scenario = str(branch.get("scenario") or RISK_SCENARIO_MAP.get(risk_type) or "S0_GENERAL_UNKNOWN")
        risk_name = str(branch.get("risk_name") or RISK_NAME_MAP.get(risk_type) or "综合风险")
        support_ids: list[str] = []
        counter_ids: list[str] = []
        missing_ids: list[str] = []

        for index, item in enumerate(branch.get("evidence_summary", []) or []):
            text = _text(item)
            if not text:
                continue
            support_ids.append(
                add_atom(
                    scenario,
                    risk_type,
                    risk_name,
                    "support",
                    f"summary_{index + 1}",
                    text,
                    str(branch.get("source") or "branch_agent"),
                    _confidence(branch.get("confidence"), 0.5),
                )
            )

        for raw_item in branch.get("field_evidence", []) or []:
            if not isinstance(raw_item, dict):
                continue
            status = str(raw_item.get("status") or "missing")
            polarity = "support" if status == "confirmed" else "counter" if status == "denied" else "missing"
            text = _text(raw_item.get("evidence_text") or raw_item.get("value") or raw_item.get("field"))
            if not text:
                continue
            atom_id = add_atom(
                scenario,
                risk_type,
                risk_name,
                polarity,
                str(raw_item.get("field") or ""),
                text,
                "field_evidence",
                _confidence(raw_item.get("confidence"), _confidence(branch.get("confidence"), 0.4)),
            )
            if polarity == "support":
                support_ids.append(atom_id)
            elif polarity == "counter":
                counter_ids.append(atom_id)
            else:
                missing_ids.append(atom_id)

        for item in branch.get("missing_evidence", []) or []:
            missing_text = _text(item, 90)
            if not missing_text:
                continue
            missing_by_scenario[scenario].append(missing_text)
            missing_ids.append(
                add_atom(
                    scenario,
                    risk_type,
                    risk_name,
                    "missing",
                    "missing_evidence",
                    missing_text,
                    "branch_agent",
                    0.0,
                )
            )

        established = bool(branch.get("established"))
        branch_score = _score(branch.get("branch_score"))
        rule_score = _score(branch.get("rule_score"))
        status = "established" if established else "insufficient_evidence" if support_ids else "not_established"
        hypotheses.append(
            RiskHypothesis(
                scenario=scenario,  # type: ignore[arg-type]
                risk_type=risk_type,
                risk_name=risk_name,
                established=established,
                rule_score=rule_score,
                branch_score=branch_score,
                confidence=_confidence(branch.get("confidence")),
                support_atom_ids=support_ids,
                counter_atom_ids=counter_ids,
                missing_atom_ids=missing_ids,
                summary=_text(branch.get("reasoning") or risk_name),
            )
        )
        assessments.append(
            ScenarioAssessment(
                scenario=scenario,  # type: ignore[arg-type]
                risk_type=risk_type,
                risk_name=risk_name,
                status=status,
                rule_score=rule_score,
                branch_score=branch_score,
                confidence=_confidence(branch.get("confidence")),
                support_evidence_count=len(support_ids),
                counter_evidence_count=len(counter_ids),
                missing_evidence=list(dict.fromkeys(missing_by_scenario[scenario]))[:6],
            )
        )

    for signal in signal_scan.negative_signals:
        scenario = signal.scenario_hint or "S0_GENERAL_UNKNOWN"
        text = "、".join(signal.matched_terms) or signal.reason
        meaning = COUNTER_SIGNAL_MEANINGS.get(signal.type, signal.reason or "负向证据")
        atom_id = add_atom(
            scenario,
            signal.type,
            signal.type,
            "counter",
            signal.type,
            text,
            "rule_negative_signal",
            abs(signal.strength),
        )
        counter_evidence.append(
            {
                "atom_id": atom_id,
                "scenario": scenario,
                "text": _text(text),
                "meaning": meaning,
                "source": "rule_negative_signal",
            }
        )

    return EvidenceGraphResult(
        evidence_graph=atoms,
        risk_hypotheses=hypotheses,
        scenario_assessments=assessments,
        counter_evidence=counter_evidence,
        missing_evidence_by_scenario={key: list(dict.fromkeys(values))[:8] for key, values in missing_by_scenario.items()},
    )


def arbitrate_cross_scenarios(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence_graph: EvidenceGraphResult,
) -> SignalScanResult:
    text = case_input.content or case_input.raw_text
    negative_types = {signal.type for signal in signal_scan.negative_signals}
    caps = list(signal_scan.cap_signals)
    decisions: list[dict[str, object]] = []

    def add_hard_cap(signal_type: str, score_cap: int, reason: str) -> None:
        if any(signal.type == signal_type for signal in caps):
            return
        caps.append(
            Signal(
                type=signal_type,
                strength=-0.5,
                score_cap=score_cap,
                cap_type="hard_cap",
                reason=reason,
            )
        )
        decisions.append({"action": "hard_cap", "type": signal_type, "score_cap": score_cap, "reason": reason})

    if {"planned_maintenance", "resolved_or_repaired"} & negative_types:
        user_pressure_terms = ["大量用户", "多个用户", "社群反馈", "投诉", "恢复时间未定", "恢复时间不明"]
        if not any(term in text for term in user_pressure_terms):
            add_hard_cap(
                "cross_scenario_planned_or_resolved_ops",
                45,
                "计划维护或已恢复语境缺少用户挤兑/长时间不可用证据，限制运维类误报。",
            )

    if "security_research_only" in negative_types:
        loss_terms = ["被盗", "盗取", "资金损失", "损失约", "攻击者", "资金外流"]
        if not any(term in text for term in loss_terms):
            add_hard_cap(
                "cross_scenario_security_research_only",
                45,
                "安全研究/审计披露缺少攻击落地和资金损失证据。",
            )

    if "discussion_only" in negative_types or "positive_regulatory_clarity" in negative_types:
        enforcement_terms = ["起诉", "罚款", "冻结", "查封", "逮捕", "禁止服务", "下架"]
        if not any(term in text for term in enforcement_terms):
            add_hard_cap(
                "cross_scenario_discussion_or_clarity",
                35,
                "讨论、咨询或监管澄清不能按已发生执法事件处理。",
            )

    debug = {
        **signal_scan.debug,
        "evidence_graph": [item.model_dump() for item in evidence_graph.evidence_graph],
        "risk_hypotheses": [item.model_dump() for item in evidence_graph.risk_hypotheses],
        "scenario_assessments": [item.model_dump() for item in evidence_graph.scenario_assessments],
        "counter_evidence": evidence_graph.counter_evidence,
        "missing_evidence_by_scenario": evidence_graph.missing_evidence_by_scenario,
        "cross_scenario_arbiter": {
            "decisions": decisions,
            "counter_signal_types": sorted(negative_types),
        },
    }
    return signal_scan.model_copy(update={"cap_signals": caps, "debug": debug})
