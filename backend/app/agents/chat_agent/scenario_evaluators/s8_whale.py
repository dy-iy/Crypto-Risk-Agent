from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing, numeric_value


def evaluate_s8(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S8_WHALE_ONCHAIN_FLOW")
    reasons: list[str] = []
    score = 0
    cap: int | None = None

    amount = numeric_value(fields, "amount_usd")
    if is_confirmed(fields, "large_transfer"):
        score = max(score, 32)
        reasons.append("large_transfer")
    if amount >= 100_000_000:
        score += 25
        reasons.append("amount_over_100m")
    elif amount >= 10_000_000:
        score += 16
        reasons.append("amount_over_10m")
    elif amount > 0:
        score += 8
        reasons.append("amount_present")
    if is_confirmed(fields, "to_exchange"):
        score += 18
        reasons.append("to_exchange")
    if is_confirmed(fields, "sell_pressure_indicated"):
        score += 16
        reasons.append("sell_pressure_indicated")
    if is_confirmed(fields, "from_exchange"):
        score += 6
        reasons.append("from_exchange")
    if is_confirmed(fields, "wallet_address"):
        score += 4
        reasons.append("wallet_address")
    if is_confirmed(fields, "internal_transfer"):
        cap = 30
        score = min(score or 12, cap)
        reasons.append("internal_transfer")

    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S8_WHALE_ONCHAIN_FLOW",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.74 if score >= 50 else 0.55 if reasons else 0.0,
        severity="high" if score >= 76 else "medium_high" if score >= 61 else "medium" if score >= 41 else "low",
        score_cap=cap,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["amount_usd", "to_exchange", "internal_transfer"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
