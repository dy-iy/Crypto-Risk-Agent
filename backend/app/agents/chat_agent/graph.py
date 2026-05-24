from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.agents.chat_agent.advice_agent import advice_agent
from app.agents.chat_agent.classify_agent import classify_agent
from app.agents.chat_agent.consistency_review_agent import consistency_review_agent
from app.agents.chat_agent.evidence_agent import evidence_agent
from app.agents.chat_agent.impact_agent import impact_agent
from app.agents.chat_agent.merge_agent import merge_results
from app.agents.chat_agent.report_agent import report_agent
from app.agents.chat_agent.risk_calibration_agent import risk_calibration_agent
from app.agents.chat_agent.risk_explanation_agent import risk_explanation_agent
from app.agents.chat_agent.score_agent import score_agent
from app.agents.chat_agent.uncertainty_agent import uncertainty_agent
from app.state import CryptoRiskState
from app.tools.chat_tools import prepare_chat_input


AgentNode = Callable[[CryptoRiskState], CryptoRiskState]

ANALYSIS_BRANCH_FIELDS = {
    "score_agent": [
        "risk_score",
        "final_risk_score",
        "severity_score",
        "confidence_score",
        "urgency_score",
        "contagion_score",
        "risk_level",
        "score_reason",
        "score_factors",
        "score_confidence",
        "score_breakdown",
    ],
    "classify_agent": [
        "primary_category",
        "secondary_categories",
        "classification_reason",
        "classification_confidence",
        "risk_categories",
    ],
    "impact_agent": [
        "impact",
        "impact_scope",
        "impact_severity",
        "affected_entities",
        "affected_assets",
        "loss_estimate",
        "systemic_risk",
        "user_asset_risk",
    ],
    "uncertainty_agent": [
        "verified_claims",
        "unverified_claims",
        "official_explanation",
        "missing_information",
        "overclaiming_risks",
    ],
}

GENERATION_BRANCH_FIELDS = {
    "risk_explanation_agent": ["risk_explanation"],
    "advice_agent": ["advice", "priority", "action_type"],
}


def _copy_for_branch(state: CryptoRiskState) -> CryptoRiskState:
    return {
        **state,
        "raw_agent_outputs": dict(state.get("raw_agent_outputs", {})),
    }


def _run_parallel(
    state: CryptoRiskState,
    branches: dict[str, AgentNode],
    field_map: dict[str, list[str]],
) -> CryptoRiskState:
    next_state: CryptoRiskState = {**state, "raw_agent_outputs": dict(state.get("raw_agent_outputs", {}))}
    with ThreadPoolExecutor(max_workers=len(branches)) as executor:
        futures = {
            name: executor.submit(node, _copy_for_branch(state))
            for name, node in branches.items()
        }
        for name, future in futures.items():
            branch_state = future.result()
            for field in field_map.get(name, []):
                if field in branch_state:
                    next_state[field] = branch_state[field]  # type: ignore[literal-required]
            next_outputs = dict(next_state.get("raw_agent_outputs", {}))
            next_outputs.update(branch_state.get("raw_agent_outputs", {}))
            next_state["raw_agent_outputs"] = next_outputs
    return next_state


class EvidenceGroundedChatWorkflow:
    def invoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        state = prepare_chat_input(initial_state)
        state = evidence_agent(state)

        state = _run_parallel(
            state,
            {
                "score_agent": score_agent,
                "classify_agent": classify_agent,
                "impact_agent": impact_agent,
                "uncertainty_agent": uncertainty_agent,
            },
            ANALYSIS_BRANCH_FIELDS,
        )

        state = merge_results(state)
        state = consistency_review_agent(state)
        state = risk_calibration_agent(state)

        state = _run_parallel(
            state,
            {
                "risk_explanation_agent": risk_explanation_agent,
                "advice_agent": advice_agent,
            },
            GENERATION_BRANCH_FIELDS,
        )
        return report_agent(state)

    async def ainvoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        return self.invoke(initial_state)


def build_chat_workflow() -> EvidenceGroundedChatWorkflow:
    return EvidenceGroundedChatWorkflow()


chat_workflow = build_chat_workflow()


def run_chat_agent(user_message: str) -> dict:
    initial_state: CryptoRiskState = {
        "original_text": user_message,
        "raw_agent_outputs": {},
    }
    result = chat_workflow.invoke(initial_state)
    return result.get("final_report", {})
