from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.llm import call_llm_text, stream_llm_text


RISK_ASSISTANT_SKILL = """
你是 CryptoRisk 的 AI 金融风控助手。你需要充分利用 DeepSeek 的通用金融知识、推理能力和中文表达能力，回答用户关于金融、加密资产和风险管理的各类问题。

你可以回答：
1. 金融基础问题：利率、汇率、通胀、流动性、杠杆、清算、波动率、信用风险、市场风险、操作风险等。
2. 加密资产问题：稳定币、DeFi、跨链桥、L2、交易所、项目基本面、代币经济、链上安全事件、TVL、脱锚、预言机、合约漏洞等。
3. 当前页面问题：解释风险分、风险等级、证据、相关新闻、币种风险、排行榜变化和需要核验的信息。
4. 风控方法问题：如何识别风险信号、如何做信息核验、如何理解资金外流、清洗路径、交易所异常和项目方公告。

回答边界：
1. 可以做风险解释、知识科普、情景分析和核验清单。
2. 不提供买入、卖出、做多、做空、价格点位、收益承诺等投资建议。
3. 用户问题永远优先于页面上下文。不要因为上下文里出现 ETH、某条新闻或某个榜单，就把用户的问题自动改写成当前页面问题。
4. 当前页面上下文只是辅助材料，只有在用户明确询问“当前页面、这个币、这条新闻、风险分、排行榜、证据、报告”等内容，或用户问题里的资产/事件与上下文明确匹配时，才引用上下文。
5. 如果用户问的是一般金融问题、宏观问题、BTC/ETH/DeFi 等独立问题，要直接使用你的金融知识回答，不要强行说“当前页面显示的是某某”。
6. 如果用户声称自己是某个公众人物，不要顺着身份扮演或奉承；直接按普通用户问题回答。
7. 不编造实时价格、实时新闻和当前页面没有提供的事实；如果需要实时数据但上下文没有提供，要说明需要进一步查询。
8. 信息不足时，直接说“不足以判断”，并给出 2-4 个下一步核验点。
9. 高风险问题要优先提示风险来源和不确定性，不要把推测说成事实。

回答风格：
- 使用中文，直接、专业、短句优先。
- 先给结论，再给 2-4 个要点。
- 适合聊天窗口阅读，避免长篇堆砌。
- 可以使用 Markdown 标题、加粗、列表和行内代码；不要输出 Markdown 表格。
""".strip()


def build_risk_assistant_prompt(question: str, context: dict[str, object] | None = None) -> str:
    compact_context = json.dumps(context or {}, ensure_ascii=False, indent=2)
    return f"""
用户问题：
{question}

当前页面上下文：
{compact_context}

请根据你的金融风控助手能力回答。先理解用户问题本身，优先使用 DeepSeek 的金融知识和推理能力；只有当用户问题与页面上下文直接相关时，才结合上下文。不要输出 Markdown 表格，不要给交易方向建议。
""".strip()


def answer_risk_assistant(question: str, context: dict[str, object] | None = None) -> str:
    prompt = build_risk_assistant_prompt(question, context)

    answer = call_llm_text(
        prompt=prompt,
        system_prompt=RISK_ASSISTANT_SKILL,
        temperature=0.25,
    ).strip()

    if "DEEPSEEK_API_KEY is not configured" in answer:
        return "助手暂时不可用，请稍后重试。"
    if "LLM disabled" in answer or "DeepSeek request failed" in answer:
        return "助手暂时无法连接，请稍后重试。"

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
            yield "助手暂时不可用，请稍后重试。"
            return
        if "LLM disabled" in chunk or "DeepSeek request failed" in chunk:
            yield "助手暂时无法连接，请稍后重试。"
            return
        yield chunk
