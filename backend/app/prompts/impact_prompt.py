from app.prompts.common import COMMON_AGENT_RULES


def build_impact_prompt(
    raw_text: str,
    triage_result: dict[str, object],
    evidence_result: dict[str, object],
    classification_result: dict[str, object],
    score_result: dict[str, object],
) -> str:
    return f"""
你是加密货币金融风控影响分析 Agent。

{COMMON_AGENT_RULES}

任务：
1. 基于 raw_text 和前序结果分析影响。
2. 不要模板硬套；没有依据时不能写用户资产损失、大规模抛售、交易所风险等过度推断。
3. 影响描述要与 evidence_result、risk_score 保持一致。
4. 必须区分“单一项目/特定配置影响”和“系统性扩散影响”。

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

请返回 JSON：
{{
  "affected_entities": ["受影响项目、交易所、协议或用户群体"],
  "affected_assets": ["受影响资产或代币"],
  "loss_estimate": "原文给出的损失估计；没有则为空字符串",
  "impact": [
    {{
      "target": "影响对象",
      "description": "基于原文证据的影响说明"
    }}
  ],
  "impact_scope": "none|short_term|long_term|protocol|market|systemic",
  "impact_severity": "none|low|medium|high",
  "systemic_risk": "none|low|medium|high",
  "user_asset_risk": "none|low|medium|high"
}}
""".strip()
