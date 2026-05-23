from __future__ import annotations

from app.llm import call_llm_json, call_llm_json_async
from app.prompts.classify_prompt import RISK_CATEGORIES
from app.services.coin_extraction_service import COIN_DICTIONARY
from app.services.data_loader import shorten
from app.services.rule_risk_scorer import risk_level_from_score, rule_risk_scorer


_ANALYSIS_CACHE: dict[str, dict[str, object]] = {}
_LLM_DISABLED = False


def _normalize_score(value: object, fallback: int) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = fallback
    return max(0, min(100, score))


def _normalize_risk_type(value: object, fallback: str) -> str:
    risk_type = str(value or "").strip()
    if risk_type in RISK_CATEGORIES:
        return risk_type
    return fallback


def _normalize_coins(value: object) -> list[str]:
    raw_symbols: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_symbols.append(item)
            elif isinstance(item, dict):
                raw_symbols.append(str(item.get("symbol", "")))

    symbols: list[str] = []
    for symbol in raw_symbols:
        normalized = symbol.strip().upper()
        if normalized in COIN_DICTIONARY and normalized not in symbols:
            symbols.append(normalized)
    return symbols


def _fallback_analysis(item: dict[str, object]) -> dict[str, object]:
    result = rule_risk_scorer(
        item.get("title", ""),
        item.get("content", ""),
        item.get("risk_level", ""),
    )
    return {
        "news_id": item.get("news_id") or item.get("id"),
        "risk_score": result["risk_score"],
        "risk_level": result["risk_level"],
        "risk_type": result["risk_type"],
        "evidence": result["evidence"],
        "summary": result["summary"],
        "coins": [],
        "source": "rule_fallback",
    }


def _build_prompt(item: dict[str, object]) -> str:
    categories = "\n".join(f"- {category}" for category in RISK_CATEGORIES)
    coin_symbols = ", ".join(COIN_DICTIONARY.keys())
    compact_item = {
        "news_id": item.get("news_id") or item.get("id"),
        "title": item.get("title", ""),
        "content": shorten(item.get("content", ""), 1200),
        "existing_risk_score": item.get("risk_score"),
        "existing_risk_level": item.get("risk_level"),
        "existing_risk_type": item.get("risk_type"),
    }

    return f"""
你是加密货币新闻风险排行榜 Agent 的 LLM 分析节点。

任务：只对下面这一条新闻进行风险评分、风险类别判断、证据摘要和币种实体提取。

规则：
1. 如果已有 risk_score 合理，可参考并校准；没有 risk_score 时根据新闻内容评分。
2. risk_score 必须是 0-100 的整数。
3. risk_level 只能是：高风险、中风险、低风险。
4. risk_type 只能从以下固定类别中选择，不允许创造新类别：
{categories}
5. coins 只能输出这些币种符号中的值：{coin_symbols}
6. 不要过度推断，不要编造新闻中没有的事实。
7. evidence 必须来自新闻内容或对新闻内容的简短归纳。
8. 一次只返回这一条新闻的标注结果，不要返回列表。

新闻：
{compact_item}

请严格返回 JSON：
{{
  "news_id": "原 news_id",
  "risk_score": 85,
  "risk_level": "高风险",
  "risk_type": "固定风险类别",
  "evidence": "风险证据或理由",
  "summary": "一句话风险摘要",
  "coins": ["BTC", "ETH"]
}}
""".strip()


def _merge_analysis(item: dict[str, object], llm_item: dict[str, object] | None) -> dict[str, object]:
    fallback = _fallback_analysis(item)
    if not llm_item:
        return fallback

    score = _normalize_score(llm_item.get("risk_score"), fallback["risk_score"])
    risk_type = _normalize_risk_type(llm_item.get("risk_type"), fallback["risk_type"])
    risk_level = str(llm_item.get("risk_level") or risk_level_from_score(score))
    if risk_level not in {"高风险", "中风险", "低风险"}:
        risk_level = risk_level_from_score(score)

    evidence = str(llm_item.get("evidence") or fallback["evidence"])
    summary = str(llm_item.get("summary") or f"{risk_type}：{evidence}")

    return {
        "news_id": item.get("news_id") or item.get("id"),
        "risk_score": score,
        "risk_level": risk_level,
        "risk_type": risk_type,
        "evidence": shorten(evidence, 180),
        "summary": shorten(summary, 130),
        "coins": _normalize_coins(llm_item.get("coins")),
        "source": "llm",
    }


def _single_item_from_result(raw_result: dict[str, object]) -> dict[str, object] | None:
    if raw_result.get("news_id") is not None:
        return raw_result

    raw_items = raw_result.get("items")
    if isinstance(raw_items, list) and raw_items:
        first_item = raw_items[0]
        if isinstance(first_item, dict):
            return dict(first_item)
    return None


def analyze_news_item_with_llm(item: dict[str, object]) -> dict[str, object]:
    global _LLM_DISABLED
    if _LLM_DISABLED:
        return _fallback_analysis(item)

    llm_result = call_llm_json(_build_prompt(item), temperature=0.1)
    if llm_result.get("_llm_error"):
        _LLM_DISABLED = True
        return _fallback_analysis(item)

    return _merge_analysis(item, _single_item_from_result(llm_result))


def analyze_news_item_with_llm_strict(item: dict[str, object]) -> dict[str, object]:
    llm_result = call_llm_json(_build_prompt(item), temperature=0.1)
    if llm_result.get("_llm_error"):
        raise RuntimeError(str(llm_result["_llm_error"]))

    return _merge_analysis(item, _single_item_from_result(llm_result))


async def analyze_news_item_with_llm_strict_async(item: dict[str, object]) -> dict[str, object]:
    llm_result = await call_llm_json_async(_build_prompt(item), temperature=0.1)
    if llm_result.get("_llm_error"):
        raise RuntimeError(str(llm_result["_llm_error"]))

    return _merge_analysis(item, _single_item_from_result(llm_result))


def analyze_news_with_llm(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    missing = [
        item
        for item in items
        if str(item.get("news_id") or item.get("id")) not in _ANALYSIS_CACHE
    ]

    for item in missing:
        news_id = str(item.get("news_id") or item.get("id"))
        _ANALYSIS_CACHE[news_id] = analyze_news_item_with_llm(item)

    return {
        str(item.get("news_id") or item.get("id")): _ANALYSIS_CACHE[
            str(item.get("news_id") or item.get("id"))
        ]
        for item in items
    }
