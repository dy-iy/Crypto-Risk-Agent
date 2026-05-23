def build_risk_detect_prompt(cleaned_text: str, entities: dict[str, list[str]]) -> str:
    return f"""
你是加密货币金融风控风险识别 Agent。

任务：
1. 判断用户文本中是否存在明显风险。
2. 抽取风险信号。
3. 只基于用户文本，不要编造事实。

用户文本：
{cleaned_text}

实体抽取结果：
{entities}

请返回 JSON：
{{
  "has_risk": true,
  "risk_signals": ["风险信号1", "风险信号2"],
  "reason": "判断理由"
}}
""".strip()
