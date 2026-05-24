from app.prompts.common import COMMON_AGENT_RULES


def build_evidence_prompt(cleaned_text: str, risk_categories: list[str]) -> str:
    return f"""
你是加密货币金融风控证据抽取 Agent。

任务：
1. 从用户原始输入中抽取证据。
2. 每个风险判断尽量对应一条或多条证据。
3. 不要编造输入中没有的事实。

用户文本：
{cleaned_text}

风险类别：
{risk_categories}

请返回 JSON：
{{
  "evidence": [
    {{
      "risk_category": "固定风险类别",
      "evidence_text": "来自用户文本的原句或短语",
      "explanation": "为什么这条证据支持该风险"
    }}
  ]
}}
""".strip()


def build_contextual_evidence_prompt(
    raw_text: str,
    cleaned_text: str,
    entities: dict[str, list[str]],
    keyword_refs: list[dict[str, str]],
    triage_result: dict[str, object],
) -> str:
    return f"""
你是加密货币金融风控证据抽取 Agent。

{COMMON_AGENT_RULES}

任务：
1. 继续阅读 raw_text 原文，并参考 risk_triage_result。
2. 先区分“原文事实”“官方说法”“社群反馈”“模型推测”，再判断证据强度。
3. 不要强行找证据；如果原文没有证据，supporting_evidence 必须为空。
4. 同时抽取 counter_evidence 和 missing_info，帮助后续 agent 避免过度推断。

raw_text：
{raw_text}

cleaned_text：
{cleaned_text}

entities：
{entities}

keyword_refs：
{keyword_refs}

risk_triage_result：
{triage_result}

请返回 JSON：
{{
  "confirmed_facts": ["原文中已经明确发生或声明的事实"],
  "risk_signals": ["直接风险信号"],
  "uncertainty_points": ["仍需验证或原文没有给出的信息"],
  "evidence_items": [
    {{
      "text": "证据原文片段",
      "source_type": "原文事实|官方说法|社群反馈|模型推测",
      "signal_type": "withdrawal_pause|confirmed_attack|actual_loss|market_impact|other",
      "supports": "支持的风险状态或结论"
    }}
  ],
  "supporting_evidence": [
    {{
      "text": "来自原文的原句或短语",
      "supports": "potential_risk|confirmed_risk|resolved_risk|uncertain|no_risk|systemic_risk",
      "evidence_type": "actual_loss|confirmed_attack|potential_threat|market_signal|operation_issue|regulatory_signal|discussion|other"
    }}
  ],
  "counter_evidence": [
    {{
      "text": "来自原文或基于原文缺失项的说明",
      "meaning": "为什么它降低风险级别或说明不足以确认"
    }}
  ],
  "missing_info": ["原文缺少的信息"],
  "evidence_quality": "strong|medium|weak|none"
}}
""".strip()
