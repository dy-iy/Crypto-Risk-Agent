from __future__ import annotations

from app.agents.chat_agent.schemas import DecisionResult, EvaluationSummary, ScenarioEvaluation


def build_fast_exit_evaluation() -> ScenarioEvaluation:
    return ScenarioEvaluation(
        scenario="S0_GENERAL_UNKNOWN",
        is_applicable=True,
        scenario_score=10,
        confidence=0.75,
        severity="low",
        reason_codes=["weak_rule_signal", "fast_exit"],
        missing_evidence=["无明确高危场景证据"],
    )


def build_fast_exit_decision() -> DecisionResult:
    return DecisionResult(
        risk_score=10,
        pre_cap_score=10,
        risk_level="低风险",
        risk_status="low_risk",
        primary_scenario="S0_GENERAL_UNKNOWN",
        confidence=0.75,
        reason_codes=["weak_rule_signal", "fast_exit"],
    )


def build_evaluation_summary(evaluations: list[ScenarioEvaluation]) -> EvaluationSummary:
    by_scenario = _best_evaluation_by_scenario(evaluations)
    merged = sorted(
        by_scenario.values(),
        key=lambda item: (item.is_applicable, item.scenario_score, item.confidence),
        reverse=True,
    )
    applicable = [item for item in merged if item.is_applicable]
    primary = _primary_candidate(applicable)
    secondary = [
        item.scenario
        for item in sorted(applicable, key=lambda item: item.scenario_score, reverse=True)
        if item.scenario != primary and item.scenario_score >= 35
    ][:3]

    return EvaluationSummary(
        merged_evaluations=merged,
        applicable_count=len(applicable),
        primary_candidate=primary,
        secondary_candidates=secondary,
        max_score=max((item.scenario_score for item in merged), default=0),
        max_confidence=max((item.confidence for item in merged), default=0.0),
        reason_codes=_unique(reason for item in applicable for reason in item.reason_codes),
        missing_evidence=_unique(missing for item in applicable for missing in item.missing_evidence),
    )


def _best_evaluation_by_scenario(evaluations: list[ScenarioEvaluation]) -> dict[str, ScenarioEvaluation]:
    by_scenario: dict[str, ScenarioEvaluation] = {}
    for evaluation in evaluations:
        current = by_scenario.get(evaluation.scenario)
        if current is None or _evaluation_rank(evaluation) > _evaluation_rank(current):
            by_scenario[evaluation.scenario] = evaluation
    return by_scenario


def _evaluation_rank(evaluation: ScenarioEvaluation) -> tuple[bool, int, float]:
    return (evaluation.is_applicable, evaluation.scenario_score, evaluation.confidence)


def _primary_candidate(applicable: list[ScenarioEvaluation]) -> str | None:
    primary_pool = [item for item in applicable if item.scenario != "S0_GENERAL_UNKNOWN"] or applicable
    if not primary_pool:
        return None
    return max(primary_pool, key=lambda item: (item.scenario_score, item.confidence)).scenario


def _unique(values) -> list[str]:
    return list(dict.fromkeys(values))
