def build_score_prompt(
    cleaned_text: str,
    risk_categories: list[str],
    evidence: list[dict[str, str]],
) -> str:
    return f"""
你是加密货币金融风控评分 Agent。

请输出 0-100 的风险分、风险等级和评分拆解。

评分等级：
0-20：低风险
21-40：轻微风险
41-60：中风险
61-80：高风险
81-100：极高风险

评分维度：
- severity：事件严重性
- evidence_strength：证据强度
- impact_scope：影响范围
- urgency：紧急程度
- reversibility：可逆性

用户文本：
{cleaned_text}

风险类别：
{risk_categories}

证据：
{evidence}

请返回 JSON：
{{
  "risk_score": 75,
  "risk_level": "高风险",
  "score_breakdown": {{
    "severity": 80,
    "evidence_strength": 70,
    "impact_scope": 75,
    "urgency": 80,
    "reversibility": 70
  }},
  "reason": "评分理由"
}}
""".strip()
