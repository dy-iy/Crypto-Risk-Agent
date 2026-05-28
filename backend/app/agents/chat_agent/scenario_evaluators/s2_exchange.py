from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing


HEAD_EXCHANGES = ["Binance", "OKX", "Coinbase", "Bybit", "Kraken", "币安", "欧易"]


def evaluate_s2(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del signal_scan
    fields = evidence.by_scenario("S2_EXCHANGE_ABNORMALITY")
    score = 0
    reasons: list[str] = []
    cap: int | None = None

    if is_confirmed(fields, "withdrawal_suspended"):
        score = max(score, 70)
        reasons.append("withdrawal_suspended")
    elif fields.get("withdrawal_suspended") and fields["withdrawal_suspended"].status == "uncertain":
        score = max(score, 28)
        reasons.append("withdrawal_suspended_uncertain")
    if is_confirmed(fields, "deposit_suspended"):
        score = max(score, 55)
        reasons.append("deposit_suspended")
    if is_confirmed(fields, "trading_halted"):
        score = max(score, 65)
        reasons.append("trading_halted")
    if is_confirmed(fields, "withdrawal_delay_only"):
        score = max(score, 45)
        reasons.append("withdrawal_delay_only")

    exchange_text = str(fields.get("affected_exchange").value if fields.get("affected_exchange") else "")
    if any(name.lower() in f"{exchange_text} {case_input.raw_text}".lower() for name in HEAD_EXCHANGES):
        score += 8
        reasons.append("major_exchange")
    if fields.get("affected_assets") and fields["affected_assets"].status == "confirmed":
        score += 5
        reasons.append("affected_assets")
    if fields.get("recovery_time") and fields["recovery_time"].status == "missing" and score:
        score += 8
        reasons.append("recovery_time_missing")
    if fields.get("fund_safety_statement") and fields["fund_safety_statement"].status == "missing" and score:
        score += 5
        reasons.append("fund_safety_statement_missing")

    if is_confirmed(fields, "planned_maintenance"):
        score = max(score - 25, 20)
        cap = 45
        reasons.append("planned_maintenance")
    if is_confirmed(fields, "recovery_time"):
        score -= 10
        reasons.append("recovery_time_confirmed")
    if is_confirmed(fields, "already_resolved"):
        score = max(score - 20, 20)
        cap = min(cap or 35, 35)
        reasons.append("already_resolved")
    if is_confirmed(fields, "fund_safety_statement"):
        score -= 15
        reasons.append("fund_safety_statement")

    if reasons and cap is not None and score <= 0:
        score = 20

    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S2_EXCHANGE_ABNORMALITY",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.82 if "withdrawal_suspended" in reasons else 0.38 if "withdrawal_suspended_uncertain" in reasons else 0.62 if reasons else 0.0,
        severity="high" if score >= 76 else "medium_high" if score >= 61 else "medium" if score >= 41 else "low",
        score_cap=cap,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["official_notice", "recovery_time", "fund_safety_statement"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
