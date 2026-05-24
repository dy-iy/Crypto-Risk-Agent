from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.llm import call_llm_text, stream_llm_text


RISK_ASSISTANT_SKILL = """
你是 CryptoRisk 的可解释风控助手，面向加密货币金融风险、项目风险、交易所风险、链上安全事件和基础金融知识问答。

能力边界：
1. 可以解释币种为何被标记为风险、风险分可能来自哪些信号、新闻/公告/链上事件的影响路径。
2. 可以回答用户的金融与加密货币基础知识问题，例如稳定币、流动性、杠杆、清算、TVL、脱锚、跨链桥攻击等。
3. 可以基于页面上下文进行解释，但不能编造没有证据支持的事实。
4. 不提供买入、卖出、做多、做空、价格点位、收益承诺等投资建议。
5. 当信息不足时，要明确说明“不足以判断”，并给出用户下一步可以补充或核验的信息。

回答风格：
- 使用中文，简洁专业。
- 优先给出直接结论，再列出 2-4 个关键理由。
- 对风险问题给出“建议关注/核验”的处置建议，但保持非投资建议口径。
- 如果用户询问具体币种，结合上下文里的风险分、风险等级、相关新闻和证据解释。
- 可以使用 Markdown 标题、加粗、列表和行内代码；不要输出 Markdown 表格。
""".strip()


def build_risk_assistant_prompt(question: str, context: dict[str, object] | None = None) -> str:
    compact_context = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return f"""
用户问题：
{question}

当前页面上下文：
{compact_context}

请根据你的风控助手技能回答。不要输出 Markdown 表格，不要给交易方向建议。
""".strip()


def answer_risk_assistant(question: str, context: dict[str, object] | None = None) -> str:
    prompt = build_risk_assistant_prompt(question, context)

    answer = call_llm_text(
        prompt=prompt,
        system_prompt=RISK_ASSISTANT_SKILL,
        temperature=0.25,
    ).strip()

    if "DEEPSEEK_API_KEY is not configured" in answer:
        return "DeepSeek API Key 尚未配置。请在 backend/app/.env 中设置 DEEPSEEK_API_KEY 后重试。"
    if "LLM disabled" in answer or "DeepSeek request failed" in answer:
        return f"暂时无法连接 DeepSeek：{answer}"

    return answer or "暂时没有生成有效回答，请换一种问法再试。"


async def stream_risk_assistant_answer(
    question: str,
    context: dict[str, object] | None = None,
) -> AsyncIterator[str]:
    prompt = build_risk_assistant_prompt(question, context)

    async for chunk in stream_llm_text(
        prompt=prompt,
        system_prompt=RISK_ASSISTANT_SKILL,
        temperature=0.25,
    ):
        if "DEEPSEEK_API_KEY is not configured" in chunk:
            yield "DeepSeek API Key 尚未配置。请在 backend/app/.env 中设置 DEEPSEEK_API_KEY 后重试。"
            return
        if "LLM disabled" in chunk or "DeepSeek request failed" in chunk:
            yield f"暂时无法连接 DeepSeek：{chunk}"
            return
        yield chunk
