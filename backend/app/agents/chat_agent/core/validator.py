from __future__ import annotations

from app.agents.chat_agent.schemas import DecisionResult, EvidenceExtractionResult, ScenarioEvaluation, ValidationSuggestion
from app.agents.chat_agent.scenario_evaluators.utils import is_confirmed, numeric_value


def need_validation(decision: DecisionResult, evaluations: list[ScenarioEvaluation]) -> bool:
    del evaluations
    cap_high_risk_conflict = bool(decision.cap_conflicts) and decision.pre_cap_score >= 60
    return (
        decision.risk_score >= 75
        or decision.confidence < 0.6
        or cap_high_risk_conflict
        or decision.pre_cap_score >= 60
    )


def validate_conflicts(decision: DecisionResult, evidence: EvidenceExtractionResult) -> ValidationSuggestion:
    scenario = decision.primary_scenario
    fields = evidence.by_scenario(scenario)
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
        }
        if planned and recovery and decision.risk_score > 45:
            return ValidationSuggestion(
                action="cap_score",
                score_cap=45,
                reason="文本说明计划维护且有恢复时间，不应判为高风险异常。",
                answered_questions=answers,
            )
        has_rumor_cap = any("rumor_without_confirmation" in item for item in decision.score_caps_applied)
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

    return ValidationSuggestion(action="no_change", reason="固定验证问题未发现需要调整的冲突。", answered_questions=answers)
