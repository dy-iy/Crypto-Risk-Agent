from app.agents.chat_agent.classify_agent import classify_agent
from app.agents.chat_agent.evidence_agent import evidence_agent
from app.agents.chat_agent.report_agent import report_agent
from app.agents.chat_agent.risk_detect_agent import risk_detect_agent
from app.agents.chat_agent.score_agent import score_agent
from app.state import CryptoRiskState
from app.tools.chat_tools import build_advice, build_impact, prepare_chat_input


try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = None
    START = None
    StateGraph = None


def conditional_router(state: CryptoRiskState) -> str:
    return "has_risk" if state.get("has_risk") else "no_risk"


class SequentialChatWorkflow:
    def invoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        state = prepare_chat_input(initial_state)
        state = risk_detect_agent(state)
        if state.get("has_risk"):
            for node in [
                classify_agent,
                evidence_agent,
                score_agent,
                build_impact,
                build_advice,
            ]:
                state = node(state)
        return report_agent(state)


def build_chat_workflow():
    if StateGraph is None:
        return SequentialChatWorkflow()

    graph = StateGraph(CryptoRiskState)
    graph.add_node("prepare_input", prepare_chat_input)
    graph.add_node("risk_detect_agent", risk_detect_agent)
    graph.add_node("classify_agent", classify_agent)
    graph.add_node("evidence_agent", evidence_agent)
    graph.add_node("score_agent", score_agent)
    graph.add_node("build_impact", build_impact)
    graph.add_node("build_advice", build_advice)
    graph.add_node("report_agent", report_agent)

    graph.add_edge(START, "prepare_input")
    graph.add_edge("prepare_input", "risk_detect_agent")
    graph.add_conditional_edges(
        "risk_detect_agent",
        conditional_router,
        {
            "no_risk": "report_agent",
            "has_risk": "classify_agent",
        },
    )
    graph.add_edge("classify_agent", "evidence_agent")
    graph.add_edge("evidence_agent", "score_agent")
    graph.add_edge("score_agent", "build_impact")
    graph.add_edge("build_impact", "build_advice")
    graph.add_edge("build_advice", "report_agent")
    graph.add_edge("report_agent", END)

    return graph.compile()


chat_workflow = build_chat_workflow()


def run_chat_agent(user_message: str) -> dict:
    initial_state: CryptoRiskState = {
        "original_text": user_message,
        "raw_agent_outputs": {},
    }
    result = chat_workflow.invoke(initial_state)
    return result.get("final_report", {})
