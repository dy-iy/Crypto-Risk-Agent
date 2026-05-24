from app.prompts.common import COMMON_AGENT_RULES


def build_advice_prompt(
    raw_text: str,
    triage_result: dict[str, object],
    evidence_result: dict[str, object],
    classification_result: dict[str, object],
    score_result: dict[str, object],
    impact_result: dict[str, object],
) -> str:
    return f"""
你是加密货币金融风控处置建议 Agent。

{COMMON_AGENT_RULES}

任务：
1. 根据风险状态、证据质量、评分和影响给建议。
2. 建议不得包含直接投资指令，例如买入、卖出、做空、梭哈。
3. 对 potential_risk / discussion_only / no actual impact，应以监测、核验、关注官方信息为主。
4. 只有 confirmed_risk 或 systemic_risk 且证据充分时，才能建议降低暴露、暂停交互等更强动作。
5. 不允许重新判断风险等级、评分或类别，只能基于已校准结果生成处置建议。

raw_text：
{raw_text}

risk_triage_result：
{triage_result}

evidence_result：
{evidence_result}

classification_result：
{classification_result}

score_result：
{score_result}

impact_result：
{impact_result}

请返回 JSON：
{{
  "advice": ["风控建议"],
  "priority": "none|low|medium|high",
  "action_type": "none|monitoring|verification|risk_reduction|urgent_response"
}}
""".strip()
