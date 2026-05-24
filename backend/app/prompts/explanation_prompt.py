from app.prompts.common import COMMON_AGENT_RULES


def build_explanation_prompt(raw_text: str, calibrated_result: dict[str, object], merged_result: dict[str, object]) -> str:
    return f"""
你是加密货币金融风控解释 Agent。

{COMMON_AGENT_RULES}

任务：
1. 只解释已确定的风险评分、风险等级和风险类别。
2. 不允许修改 risk_score、risk_level、risk_categories。
3. 语气专业、简洁，适合聊天窗口展示。
4. risk_explanation 最多 80 个中文字符，只写一句事件结论。
5. 不要展开评分拆解，不要解释 risk_score/confidence_score 的定义，不要写“右侧已生成”“可点击查看完整报告”等界面提示。

raw_text：
{raw_text}

calibrated_result：
{calibrated_result}

merged_result：
{merged_result}

请返回 JSON：
{{
  "risk_explanation": "一句话风险结论"
}}
""".strip()
