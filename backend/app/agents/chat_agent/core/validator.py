from __future__ import annotations

from app.agents.chat_agent.core.evidence_utils import is_confirmed, numeric_value
from typing import Any

from app.agents.chat_agent.schemas import (
    DecisionResult,
    EvidenceExtractionResult,
    EvidenceGraphResult,
    ValidationSuggestion,
)


def need_validation(decision: DecisionResult) -> bool:
    cap_high_risk_conflict = bool(decision.cap_conflicts) and decision.pre_cap_score >= 60
    return (
        decision.risk_score >= 75
        or decision.confidence < 0.6
        or cap_high_risk_conflict
        or decision.pre_cap_score >= 60
    )


def _graph_context(raw_graph: EvidenceGraphResult | dict[str, Any] | None, scenario: str) -> dict[str, Any]:
    if raw_graph is None:
        return {
            "support_count": 0,
            "counter_count": 0,
            "missing": [],
            "counter_text": "",
        }
    graph = raw_graph if isinstance(raw_graph, EvidenceGraphResult) else EvidenceGraphResult.model_validate(raw_graph)
    support_count = 0
    counter_count = 0
    for atom in graph.evidence_graph:
        if atom.scenario != scenario:
            continue
        if atom.polarity == "support":
            support_count += 1
        elif atom.polarity == "counter":
            counter_count += 1
    counter_items = [
        str(item.get("meaning") or item.get("text") or "")
        for item in graph.counter_evidence
        if str(item.get("scenario") or scenario) == scenario
    ]
    return {
        "support_count": support_count,
        "counter_count": counter_count,
        "missing": graph.missing_evidence_by_scenario.get(scenario, []),
        "counter_text": "；".join(counter_items),
    }


def validate_conflicts(
    decision: DecisionResult,
    evidence: EvidenceExtractionResult,
    evidence_graph: EvidenceGraphResult | dict[str, Any] | None = None,
) -> ValidationSuggestion:
    scenario = decision.primary_scenario
    fields = evidence.by_scenario(scenario)
    graph = _graph_context(evidence_graph, scenario)
    answers: dict[str, object] = {}

    if scenario == "S1_ATTACK_EXPLOIT":
        exploit = is_confirmed(fields, "exploit_occurred")
        loss = numeric_value(fields, "loss_usd")
        research_only = is_confirmed(fields, "is_security_research_only")
        mitigated = is_confirmed(fields, "mitigation_status")
        answers = {
            "exploit_occurred": exploit,
            "loss_usd": loss,
            "security_research_only": research_only,
            "mitigated": mitigated,
        }
        if decision.risk_score >= 60 and research_only and not exploit and not loss:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="文本更像安全研究或漏洞披露，未确认攻击发生和资金损失。",
                answered_questions=answers,
            )
        if exploit and loss >= 10_000_000:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=76,
                reason="文本明确说明攻击发生并包含可量化大额损失。",
                answered_questions=answers,
            )

    if scenario == "S2_EXCHANGE_ABNORMALITY":
        withdrawal = is_confirmed(fields, "withdrawal_suspended")
        planned = is_confirmed(fields, "planned_maintenance")
        recovery = is_confirmed(fields, "recovery_time")
        safe = is_confirmed(fields, "fund_safety_statement")
        answers = {
            "withdrawal_suspended": withdrawal,
            "planned_maintenance": planned,
            "recovery_time": recovery,
            "fund_safety_statement": safe,
            "graph_support_count": graph["support_count"],
            "graph_counter_count": graph["counter_count"],
        }
        if planned and recovery and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="文本说明计划维护且有恢复时间，不应判为高风险异常。",
                answered_questions=answers,
            )
        has_rumor_cap = any("rumor_without_confirmation" in item for item in decision.score_caps_applied)
        if "计划维护" in str(graph["counter_text"]) and graph["support_count"] <= 1 and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="证据图谱显示计划维护类反证强于交易所危机证据。",
                answered_questions=answers,
            )
        if withdrawal and not recovery and decision.risk_score < 68 and not has_rumor_cap:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=68,
                reason="文本明确暂停提现且缺少恢复时间，用户资产可得性风险需要评分下限。",
                answered_questions=answers,
            )

    if scenario == "S5_REGULATORY_ENFORCEMENT":
        discussion = is_confirmed(fields, "is_policy_discussion_only")
        clarity = is_confirmed(fields, "is_positive_regulatory_clarity")
        action = is_confirmed(fields, "enforcement_action")
        answers = {
            "policy_discussion_only": discussion,
            "positive_regulatory_clarity": clarity,
            "enforcement_action": action,
        }
        if (discussion or clarity) and decision.risk_score > 30:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=30 if discussion else 20,
                reason="文本为监管讨论或监管利好，缺少明确执法动作。",
                answered_questions=answers,
            )

    if scenario == "S6_MARKET_LIQUIDATION":
        commentary = is_confirmed(fields, "is_normal_market_commentary")
        forecast = is_confirmed(fields, "is_forecast_only")
        answers = {"normal_market_commentary": commentary, "forecast_only": forecast}
        if (commentary or forecast) and decision.risk_score > 35:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=25 if commentary else 35,
                reason="文本为普通行情评论或预测，不是已发生高危市场事件。",
                answered_questions=answers,
            )

    if scenario == "S4_INFRASTRUCTURE_FAILURE":
        resolved = is_confirmed(fields, "already_resolved")
        funds = is_confirmed(fields, "funds_at_risk")
        stopped = is_confirmed(fields, "block_production_stopped")
        answers = {"already_resolved": resolved, "funds_at_risk": funds, "block_production_stopped": stopped}
        if resolved and not funds and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="基础设施异常已恢复，且未确认资金风险。",
                answered_questions=answers,
            )

    if scenario == "S7_FRAUD_GOVERNANCE":
        ordinary = is_confirmed(fields, "is_ordinary_team_change")
        phishing = is_confirmed(fields, "phishing_site") or is_confirmed(fields, "fake_airdrop")
        loss = is_confirmed(fields, "user_loss_confirmed")
        answers = {"ordinary_team_change": ordinary, "phishing_or_fake_airdrop": phishing, "user_loss_confirmed": loss}
        if ordinary and not phishing and not loss and decision.risk_score > 35:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=35,
                reason="文本为普通团队变动，缺少诈骗、跑路或资金受损证据。",
                answered_questions=answers,
            )
        if phishing and loss and decision.risk_score < 70:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=70,
                reason="文本同时确认钓鱼/假空投和用户损失。",
                answered_questions=answers,
            )

    if scenario == "S8_WHALE_ONCHAIN_FLOW":
        internal = is_confirmed(fields, "internal_transfer")
        to_exchange = is_confirmed(fields, "to_exchange")
        sell_pressure = is_confirmed(fields, "sell_pressure_indicated")
        answers = {"internal_transfer": internal, "to_exchange": to_exchange, "sell_pressure_indicated": sell_pressure}
        if internal and not sell_pressure and decision.risk_score > 30:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=30,
                reason="文本为内部归集或钱包迁移，不应直接视作外部抛压。",
                answered_questions=answers,
            )
        if to_exchange and sell_pressure and decision.risk_score < 55:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=55,
                reason="大额资产流入交易所且文本指向潜在卖压。",
                answered_questions=answers,
            )

    if scenario == "S9_TOKEN_ISSUANCE_ANOMALY":
        unauthorized = is_confirmed(fields, "unauthorized_mint")
        abnormal_supply = is_confirmed(fields, "abnormal_supply_increase")
        exploited = is_confirmed(fields, "exploited_vulnerability")
        governance_approved = is_confirmed(fields, "governance_approved")
        mitigated = is_confirmed(fields, "mitigation_status")
        user_fund_affected = is_confirmed(fields, "user_fund_affected")
        mint_value = numeric_value(fields, "mint_amount_usd")
        answers = {
            "unauthorized_mint": unauthorized,
            "abnormal_supply_increase": abnormal_supply,
            "exploited_vulnerability": exploited,
            "governance_approved": governance_approved,
            "mitigated": mitigated,
            "user_fund_affected": user_fund_affected,
            "mint_amount_usd": mint_value,
            "graph_support_count": graph["support_count"],
            "graph_counter_count": graph["counter_count"],
            "graph_missing": graph["missing"],
        }
        if governance_approved and not unauthorized and not exploited and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="文本更像治理批准或计划内供应调整，未确认未授权铸造。",
                answered_questions=answers,
            )
        if mitigated and not user_fund_affected and decision.risk_score > 55:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=55,
                reason="异常增发已处置且未确认用户资产受损。",
                answered_questions=answers,
            )
        if (unauthorized or exploited) and (abnormal_supply or mint_value >= 1_000_000) and decision.risk_score < 76:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=76,
                reason="文本确认未授权铸造/漏洞利用，并存在供应或可变现风险。",
                answered_questions=answers,
            )

    if scenario == "S10_BRIDGE_CROSS_CHAIN_RISK":
        bridge_attack = is_confirmed(fields, "bridge_attack")
        bridge_paused = is_confirmed(fields, "bridge_paused")
        asset_outflow = is_confirmed(fields, "asset_outflow")
        loss = numeric_value(fields, "loss_usd")
        funds_at_risk = is_confirmed(fields, "funds_at_risk")
        resolved = is_confirmed(fields, "already_resolved")
        answers = {
            "bridge_attack": bridge_attack,
            "bridge_paused": bridge_paused,
            "asset_outflow": asset_outflow,
            "loss_usd": loss,
            "funds_at_risk": funds_at_risk,
            "already_resolved": resolved,
            "graph_support_count": graph["support_count"],
            "graph_counter_count": graph["counter_count"],
            "graph_missing": graph["missing"],
        }
        if resolved and bridge_paused and not asset_outflow and not funds_at_risk and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="跨链桥暂停已恢复且未确认资金外流或资金风险。",
                answered_questions=answers,
            )
        if "计划维护" in str(graph["counter_text"]) and not asset_outflow and not funds_at_risk and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="证据图谱显示跨链桥计划维护反证，未确认攻击、资金外流或资金风险。",
                answered_questions=answers,
            )
        if bridge_attack and (asset_outflow or loss >= 1_000_000 or funds_at_risk) and decision.risk_score < 76:
            return ValidationSuggestion(
                action="raise_floor",
                score_floor=76,
                reason="文本确认跨链桥攻击并存在资产外流或资金风险。",
                answered_questions=answers,
            )

    return ValidationSuggestion(action="no_change", reason="固定验证问题未发现需要调整的冲突。", answered_questions=answers)
