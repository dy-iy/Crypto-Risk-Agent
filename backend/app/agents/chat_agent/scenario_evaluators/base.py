from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.agents.chat_agent.schemas import (
    EvidenceExtractionResult,
    RiskCaseInput,
    ScenarioEvaluation,
    ScenarioHypothesis,
    ScenarioId,
    SignalScanResult,
)
from app.agents.chat_agent.scenario_evaluators.s0_general import evaluate_s0
from app.agents.chat_agent.scenario_evaluators.s1_attack import evaluate_s1
from app.agents.chat_agent.scenario_evaluators.s2_exchange import evaluate_s2
from app.agents.chat_agent.scenario_evaluators.s3_stablecoin import evaluate_s3
from app.agents.chat_agent.scenario_evaluators.s4_infra import evaluate_s4
from app.agents.chat_agent.scenario_evaluators.s5_regulatory import evaluate_s5
from app.agents.chat_agent.scenario_evaluators.s6_market import evaluate_s6
from app.agents.chat_agent.scenario_evaluators.s7_fraud import evaluate_s7
from app.agents.chat_agent.scenario_evaluators.s8_whale import evaluate_s8


Evaluator = callable

EVALUATORS = {
    "S0_GENERAL_UNKNOWN": evaluate_s0,
    "S1_ATTACK_EXPLOIT": evaluate_s1,
    "S2_EXCHANGE_ABNORMALITY": evaluate_s2,
    "S3_STABLECOIN_RESERVE": evaluate_s3,
    "S4_INFRASTRUCTURE_FAILURE": evaluate_s4,
    "S5_REGULATORY_ENFORCEMENT": evaluate_s5,
    "S6_MARKET_LIQUIDATION": evaluate_s6,
    "S7_FRAUD_GOVERNANCE": evaluate_s7,
    "S8_WHALE_ONCHAIN_FLOW": evaluate_s8,
}


def _unsupported(scenario: ScenarioId) -> ScenarioEvaluation:
    return ScenarioEvaluation(
        scenario=scenario,
        is_applicable=False,
        scenario_score=0,
        confidence=0.0,
        severity="none",
        reason_codes=["scenario_not_implemented_in_phase_1"],
    )


def evaluate_scenarios(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
    hypotheses: list[ScenarioHypothesis],
) -> list[ScenarioEvaluation]:
    def run(hypothesis: ScenarioHypothesis) -> ScenarioEvaluation:
        evaluator = EVALUATORS.get(hypothesis.scenario)
        if evaluator is None:
            return _unsupported(hypothesis.scenario)
        return evaluator(case_input, signal_scan, evidence)

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(hypotheses)))) as executor:
        return list(executor.map(run, hypotheses))
