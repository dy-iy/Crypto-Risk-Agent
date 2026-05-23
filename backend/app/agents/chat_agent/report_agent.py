from app.llm import call_llm_json
from app.prompts.report_prompt import build_report_prompt
from app.state import CryptoRiskState


def _default_summary(state: CryptoRiskState) -> str:
    if not state.get("has_risk"):
        return "暂未从输入文本中发现明显加密货币风险信号。"

    categories = state.get("risk_categories", [])
    score = state.get("risk_score", 0)
    level = state.get("risk_level", "低风险")
    category_text = "、".join(categories) if categories else "未分类风险"
    return f"识别到{category_text}，综合风险评分为 {score}，风险等级为{level}。"


def report_agent(state: CryptoRiskState) -> CryptoRiskState:
    llm_result = call_llm_json(build_report_prompt(dict(state)))

    summary = str(llm_result.get("summary") or _default_summary(state))
    impact = llm_result.get("impact") if isinstance(llm_result.get("impact"), list) else state.get("impact", [])
    advice = llm_result.get("advice") if isinstance(llm_result.get("advice"), list) else state.get("advice", [])

    if not state.get("has_risk"):
        impact = []
        advice = ["继续核实信息来源，关注后续官方公告和链上数据变化。"]

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["report_agent"] = llm_result

    final_report = {
        "summary": summary,
        "input_type": state.get("input_type", "unknown"),
        "has_risk": bool(state.get("has_risk", False)),
        "risk_score": int(state.get("risk_score", 0)),
        "risk_level": state.get("risk_level", "低风险"),
        "risk_categories": state.get("risk_categories", []),
        "risk_signals": state.get("risk_signals", []),
        "entities": state.get("entities", {}),
        "evidence": state.get("evidence", []),
        "score_breakdown": state.get("score_breakdown", {}),
        "impact": [str(item) for item in impact],
        "advice": [str(item) for item in advice],
        "raw_agent_outputs": raw_outputs,
    }

    return {
        **state,
        "impact": final_report["impact"],
        "advice": final_report["advice"],
        "final_report": final_report,
        "raw_agent_outputs": raw_outputs,
    }
