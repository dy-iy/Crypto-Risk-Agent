from app.prompts.common import COMMON_AGENT_RULES


def build_review_prompt(
    raw_text: str,
    triage_result: dict[str, object],
    evidence_result: dict[str, object],
    classification_result: dict[str, object],
    score_result: dict[str, object],
    impact_result: dict[str, object],
    advice_result: dict[str, object],
) -> str:
    return f"""
你是加密货币金融风控一致性审查 Agent。

{COMMON_AGENT_RULES}

审查重点：
- risk_status = no_risk，但 score > 30？
- evidence_quality = none，但 score > 50？
- confirmed_risk=false，却写了“已发生攻击”？
- 原文只是讨论长期风险，却建议立即撤资？
- 没有市场数据，却写“造成市场恐慌”？
- advice 是否超过 raw_text 证据支持范围？
- 原文明确为已确认攻击且损失超过 1 亿美元，但 score < 80？
- 原文存在 Lazarus/国家级黑客归因、RPC/验证网络/跨链基础设施攻击路径，但评分和影响分析没有体现严重性？

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

advice_result：
{advice_result}

请返回 JSON：
{{
  "has_conflict": false,
  "issues": [],
  "revision_suggestions": []
}}
""".strip()
