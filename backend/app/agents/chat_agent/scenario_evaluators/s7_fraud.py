from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing


def evaluate_s7(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S7_FRAUD_GOVERNANCE")
    score = 0
    reasons: list[str] = []
    cap: int | None = None
    floor: int | None = None

    if is_confirmed(fields, "phishing_site"):
        score = max(score, 58)
        reasons.append("phishing_site")
    if is_confirmed(fields, "fake_airdrop"):
        score = max(score, 54)
        reasons.append("fake_airdrop")
    if is_confirmed(fields, "impersonation"):
        score = max(score, 50)
        reasons.append("impersonation")
    if is_confirmed(fields, "fake_token"):
        score = max(score, 48)
        reasons.append("fake_token")
    if is_confirmed(fields, "wallet_connection_lure"):
        score += 12
        reasons.append("wallet_connection_lure")
    if is_confirmed(fields, "fraud_claim"):
        score = max(score, 55)
        reasons.append("fraud_claim")
    if is_confirmed(fields, "user_loss_confirmed"):
        score += 18
        floor = 70
        reasons.append("user_loss_confirmed")
    if is_confirmed(fields, "rug_pull_or_exit"):
        score = max(score, 82)
        floor = 76
        reasons.append("rug_pull_or_exit")
    if is_confirmed(fields, "team_missing"):
        score += 8
        reasons.append("team_missing")
    if is_confirmed(fields, "funds_removed"):
        score += 15
        floor = max(floor or 0, 72)
        reasons.append("funds_removed")
    if is_confirmed(fields, "official_response"):
        score += 4
        reasons.append("official_response")
    if is_confirmed(fields, "is_ordinary_team_change"):
        cap = 35
        score = min(score or 20, cap)
        reasons.append("ordinary_team_change")

    if floor is not None:
        score = max(score, floor)
    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S7_FRAUD_GOVERNANCE",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.82 if score >= 70 else 0.68 if reasons else 0.0,
        severity="high" if score >= 76 else "medium_high" if score >= 61 else "medium" if score >= 41 else "low",
        score_cap=cap,
        score_floor=floor,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["official_response", "user_loss_confirmed", "funds_removed"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
