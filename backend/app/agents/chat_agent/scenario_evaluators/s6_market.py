from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing, numeric_value


def evaluate_s6(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S6_MARKET_LIQUIDATION")
    reasons: list[str] = []
    cap: int | None = None
    score = 0

    pct = numeric_value(fields, "price_drop_pct")
    liquidation_usd = numeric_value(fields, "liquidation_amount_usd")
    if pct >= 20:
        score = max(score, 72)
        reasons.append("large_price_drop")
    elif pct >= 8:
        score = max(score, 50)
        reasons.append("price_drop")
    if liquidation_usd >= 100_000_000:
        score = max(score, 76)
        reasons.append("large_liquidation")
    elif liquidation_usd >= 10_000_000:
        score = max(score, 58)
        reasons.append("liquidation_amount")
    if is_confirmed(fields, "liquidity_stress_mentioned"):
        score += 12
        reasons.append("liquidity_stress")
    if is_confirmed(fields, "market_scope"):
        score += 5
        reasons.append("market_scope")
    if is_confirmed(fields, "is_normal_market_commentary"):
        score = max(score, 12)
        cap = 25
        reasons.append("normal_market_commentary")
    if is_confirmed(fields, "is_forecast_only"):
        score = max(score, 18)
        cap = min(cap or 35, 35)
        reasons.append("forecast_only")

    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S6_MARKET_LIQUIDATION",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.72 if score >= 58 else 0.5 if reasons else 0.0,
        severity="high" if score >= 76 else "medium" if score >= 41 else "low",
        score_cap=cap,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["price_drop_pct", "liquidation_amount_usd", "market_scope"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
