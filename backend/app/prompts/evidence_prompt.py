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
