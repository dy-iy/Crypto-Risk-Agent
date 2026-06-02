from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from app.agents.daily_report_agent.state import DailyReportState
from app.agents.ranking_agent.graph import run_ranking_agent
from app.llm import call_llm_json
from app.services.auth_service import list_favorites
from app.services.portfolio_service import DEFAULT_USER_ID
from app.services.user_asset_service import list_user_assets


FORBIDDEN_ADVICE_TERMS = ["买入", "卖出", "做空", "梭哈"]


def _clamp_score(value: object) -> int:
    try:
        return max(0, min(100, round(float(value or 0))))
    except (TypeError, ValueError):
        return 0


def _risk_level_from_score(score: int) -> str:
    if score >= 90:
        return "红色预警"
    if score >= 80:
        return "高风险"
    if score >= 40:
        return "中风险"
    return "低风险"


def _is_high_risk_news(item: dict[str, object]) -> bool:
    level = str(item.get("risk_level") or "")
    if "中高" in level:
        return False
    return "高" in level or "红" in level or _clamp_score(item.get("risk_score")) >= 80


def _is_red_alert_news(item: dict[str, object]) -> bool:
    level = str(item.get("risk_level") or "")
    return "红" in level or _clamp_score(item.get("risk_score")) >= 90


def _normalize_risk_type(value: object) -> str:
    text = str(value or "综合风险").strip().replace("｜", "/").replace("|", "/")
    return "".join(text.split()) or "综合风险"


def _first_text(item: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _base_asset(symbol: object) -> str:
    text = str(symbol or "").strip().upper()
    return text[:-4] if text.endswith("USDT") else text


def _contains_asset_token(text: str, asset: str) -> bool:
    if not asset:
        return False
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(asset)}(?![A-Z0-9])", text))


def _exposure_weight(asset: dict[str, object]) -> float:
    if asset.get("exposure_mode") == "custom" and asset.get("custom_exposure_pct") is not None:
        try:
            return max(0.0, min(1.0, float(asset.get("custom_exposure_pct") or 0)))
        except (TypeError, ValueError):
            return 0.0
    if asset.get("is_holding"):
        try:
            market_value = float(asset.get("market_value") or 0)
        except (TypeError, ValueError):
            market_value = 0
        if market_value > 0:
            return 0.75
        return 0.55
    bucket = str(asset.get("exposure_bucket") or "none")
    return {"high": 0.75, "medium": 0.45, "low": 0.25, "none": 0.12}.get(bucket, 0.12)


def _asset_profile_item(item: object) -> dict[str, object]:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
    symbol = str(data.get("symbol") or "").upper()
    return {
        "symbol": symbol,
        "base_asset": str(data.get("base_asset") or _base_asset(symbol)).upper(),
        "is_watched": bool(data.get("is_watched", True)),
        "is_holding": bool(data.get("is_holding", False)),
        "exposure_mode": str(data.get("exposure_mode") or "bucket"),
        "exposure_bucket": str(data.get("exposure_bucket") or "none"),
        "custom_exposure_pct": data.get("custom_exposure_pct"),
        "amount": float(data.get("amount") or 0),
        "avg_buy_price": float(data.get("avg_buy_price") or 0),
        "alert_threshold": int(data.get("alert_threshold") or 70),
        "current_price": float(data.get("current_price") or 0),
        "price_change_24h": float(data.get("price_change_24h") or 0),
        "market_value": float(data.get("market_value") or 0),
        "floating_pnl": float(data.get("floating_pnl") or 0),
        "floating_pnl_rate": float(data.get("floating_pnl_rate") or 0),
        "existing_risk_score": _clamp_score(data.get("risk_score")),
        "existing_risk_level": str(data.get("risk_level") or "low"),
        "ai_summary": str(data.get("ai_summary") or ""),
    }


def _favorite_brief(item: object) -> dict[str, object]:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    return {
        "item_id": str(data.get("item_id") or ""),
        "title": str(data.get("title") or "")[:160],
        "risk_score": _clamp_score(payload.get("risk_score")),
        "risk_level": str(payload.get("risk_level") or ""),
        "risk_type": str(payload.get("risk_type") or ""),
        "created_at": str(data.get("created_at") or ""),
    }


def _sanitize_actions(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    actions = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if any(term in text for term in FORBIDDEN_ADVICE_TERMS):
            continue
        actions.append(text)
    return actions[:6]


def _news_asset_match(item: dict[str, object], assets: list[dict[str, object]]) -> tuple[list[str], float, str]:
    if not assets:
        return [], 0, ""

    raw_coins = item.get("coins") if isinstance(item.get("coins"), list) else []
    coin_values = {str(coin or "").upper() for coin in raw_coins}
    raw_details = item.get("coin_details") if isinstance(item.get("coin_details"), list) else []
    for detail in raw_details:
        if isinstance(detail, dict):
            coin_values.add(str(detail.get("symbol") or "").upper())

    title = str(item.get("title") or "")
    content = str(item.get("content") or item.get("summary") or "")
    text_upper = f"{title}\n{content}".upper()
    matched_assets = []
    relevance = 0.0
    reasons = []

    for asset in assets:
        symbol = str(asset.get("symbol") or "").upper()
        base = str(asset.get("base_asset") or _base_asset(symbol)).upper()
        matched = False
        if symbol in coin_values or base in coin_values:
            matched = True
            relevance = max(relevance, 0.95)
            reasons.append(f"{base}实体字段命中")
        elif _contains_asset_token(text_upper, base):
            matched = True
            relevance = max(relevance, 0.72)
            reasons.append(f"{base}文本命中")
        if matched:
            matched_assets.append(base or symbol)

    return list(dict.fromkeys(matched_assets)), relevance, "；".join(dict.fromkeys(reasons))


def _personal_news_score(item: dict[str, object], matched_assets: list[str], user_assets: list[dict[str, object]], relevance: float) -> int:
    base_score = _clamp_score(item.get("risk_score"))
    if not matched_assets:
        return 0
    asset_weight = 0.12
    for asset in user_assets:
        base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
        if base in matched_assets:
            asset_weight = max(asset_weight, _exposure_weight(asset))
    return _clamp_score(base_score * (0.55 + relevance * 0.25 + asset_weight * 0.35))


def _exposure_note(matched_assets: list[str], user_assets: list[dict[str, object]]) -> str:
    notes = []
    for asset in user_assets:
        base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
        if base not in matched_assets:
            continue
        if asset.get("is_holding"):
            notes.append(f"{base}为持仓资产")
        else:
            notes.append(f"{base}为关注资产")
    return "，".join(notes)


def _key_news(
    items: list[dict[str, object]],
    user_assets: list[dict[str, object]] | None = None,
    limit: int | None = 5,
) -> list[dict[str, object]]:
    user_assets = user_assets or []
    if user_assets:
        enriched = []
        for item in items:
            matched_assets, relevance, match_reason = _news_asset_match(item, user_assets)
            personal_score = _personal_news_score(item, matched_assets, user_assets, relevance)
            if matched_assets:
                enriched.append(
                    {
                        **item,
                        "_matched_assets": matched_assets,
                        "_personal_relevance": relevance,
                        "_personal_score": personal_score,
                        "_match_reason": match_reason,
                    }
                )
        ranked = sorted(
            enriched,
            key=lambda item: (_clamp_score(item.get("_personal_score")), _clamp_score(item.get("risk_score"))),
            reverse=True,
        )
    else:
        ranked = sorted(items, key=lambda item: _clamp_score(item.get("risk_score")), reverse=True)

    output = []
    selected_items = ranked[:limit] if limit else ranked
    for item in selected_items:
        matched_assets = [str(asset) for asset in item.get("_matched_assets", [])]
        personal_score = _clamp_score(item.get("_personal_score")) if matched_assets else _clamp_score(item.get("risk_score"))
        output.append(
            {
                "news_id": str(item.get("news_id") or ""),
                "title": str(item.get("title") or "未命名风险事件"),
                "summary": _first_text(item, "summary", "evidence", "content"),
                "evidence": str(item.get("evidence") or ""),
                "risk_score": _clamp_score(item.get("risk_score")),
                "personal_score": personal_score,
                "risk_level": str(item.get("risk_level") or _risk_level_from_score(_clamp_score(item.get("risk_score")))),
                "risk_type": _normalize_risk_type(item.get("risk_type")),
                "published_at": str(item.get("published_at") or item.get("date") or ""),
                "coins": [str(coin) for coin in item.get("coins", []) if coin],
                "matched_assets": matched_assets,
                "personal_relevance": float(item.get("_personal_relevance") or 0),
                "matched_reason": str(item.get("_match_reason") or ""),
                "exposure_note": _exposure_note(matched_assets, user_assets) if matched_assets else "",
            }
        )
    return output


def _risk_type_stats(items: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "high_count": 0, "max_score": 0})
    for item in items:
        name = _normalize_risk_type(item.get("risk_type"))
        score = _clamp_score(item.get("risk_score"))
        grouped[name]["count"] += 1
        grouped[name]["high_count"] += 1 if _is_high_risk_news(item) else 0
        grouped[name]["max_score"] = max(grouped[name]["max_score"], score)

    max_count = max((value["count"] for value in grouped.values()), default=1)
    stats = [
        {
            "name": name,
            "count": value["count"],
            "high_count": value["high_count"],
            "max_score": value["max_score"],
            "weight": max(8, round(value["count"] / max_count * 100)),
        }
        for name, value in grouped.items()
    ]
    return sorted(stats, key=lambda item: (int(item["max_score"]), int(item["count"])), reverse=True)[:5]


def _risk_themes_from_key_news(items: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        assets = [str(asset).upper() for asset in item.get("matched_assets", [])]
        asset_key = ",".join(assets[:3]) or "GLOBAL"
        grouped[(_normalize_risk_type(item.get("risk_type")), asset_key)].append(item)

    themes = []
    for index, ((risk_type, asset_key), group_items) in enumerate(grouped.items(), start=1):
        affected_assets = [] if asset_key == "GLOBAL" else asset_key.split(",")
        max_score = max((_clamp_score(item.get("personal_score") or item.get("risk_score")) for item in group_items), default=0)
        evidence_summary = [
            str(item.get("evidence") or item.get("summary") or "").strip()
            for item in group_items
            if str(item.get("evidence") or item.get("summary") or "").strip()
        ][:3]
        themes.append(
            {
                "theme_id": f"theme-{index}",
                "title": f"{'、'.join(affected_assets) if affected_assets else '全市场'}：{risk_type}",
                "risk_type": risk_type,
                "affected_assets": affected_assets,
                "event_count": len(group_items),
                "max_personal_score": max_score,
                "risk_level": _risk_level_from_score(max_score),
                "summary": f"{risk_type}相关事件集中影响 {'、'.join(affected_assets) if affected_assets else '市场情绪'}，需要结合证据强度与后续公告确认。",
                "evidence_summary": evidence_summary,
                "monitoring_items": [
                    "官方公告与交易所状态变化",
                    "链上大额转账、提现与流动性异常",
                    "同类风险事件是否继续扩散",
                ],
                "source_event_count": len(group_items),
                "source_news_ids": [str(item.get("news_id") or "") for item in group_items if item.get("news_id")],
            }
        )

    return sorted(themes, key=lambda item: (int(item["max_personal_score"]), int(item["event_count"])), reverse=True)[:4]


def _merge_llm_risk_themes(llm_items: object, fallback_themes: list[dict[str, object]]) -> list[dict[str, object]]:
    if not isinstance(llm_items, list):
        return fallback_themes

    merged = []
    for index, fallback in enumerate(fallback_themes):
        llm_item = llm_items[index] if index < len(llm_items) and isinstance(llm_items[index], dict) else {}
        merged.append(
            {
                **fallback,
                "title": str(llm_item.get("title") or fallback.get("title")),
                "summary": str(llm_item.get("summary") or fallback.get("summary")),
                "severity_reason": str(llm_item.get("severity_reason") or ""),
                "monitoring_items": [
                    str(item).strip()
                    for item in llm_item.get("monitoring_items", fallback.get("monitoring_items", []))
                    if str(item).strip()
                ][:5],
            }
        )
    return merged


def _asset_exposure_label(asset: dict[str, object]) -> str:
    base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
    if asset.get("is_holding"):
        return f"{base} 持仓资产"
    return f"{base} 关注资产"


def _asset_related_items(asset: dict[str, object], key_news: list[dict[str, object]]) -> list[dict[str, object]]:
    base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
    return [
        item
        for item in key_news
        if base in {str(value).upper() for value in item.get("matched_assets", [])}
    ]


def _fallback_asset_actions(asset: dict[str, object], related_items: list[dict[str, object]], score: int) -> list[str]:
    base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
    if related_items:
        actions = [
            f"核验 {base} 相关公告、交易所充提状态与链上大额转账。",
            f"对 {base} 设置价格波动、新闻连续命中和风险分阈值提醒。",
            "避免依据单条未证实消息做方向性操作，等待多源证据确认。",
        ]
        if score >= int(asset.get("alert_threshold") or 70):
            actions.insert(0, f"{base} 已达到或接近你的风险阈值，优先复核持仓暴露和流动性。")
        return actions
    return [
        f"今日新闻库暂未命中 {base} 的直接风险事件。",
        f"继续监控 {base} 官方公告、交易所状态和链上异常。",
    ]


def _asset_reports_from_profile(
    user_assets: list[dict[str, object]],
    key_news: list[dict[str, object]],
) -> list[dict[str, object]]:
    reports = []
    for asset in user_assets:
        symbol = str(asset.get("symbol") or "").upper()
        base = str(asset.get("base_asset") or _base_asset(symbol)).upper()
        related_items = _asset_related_items(asset, key_news)
        related_scores = [_clamp_score(item.get("personal_score") or item.get("risk_score")) for item in related_items]
        score = max(related_scores, default=_clamp_score(asset.get("existing_risk_score")))
        risk_types = list(dict.fromkeys(_normalize_risk_type(item.get("risk_type")) for item in related_items))
        evidence_summary = [
            str(item.get("evidence") or item.get("summary") or "").strip()
            for item in related_items
            if str(item.get("evidence") or item.get("summary") or "").strip()
        ][:4]
        key_drivers = [
            f"{_normalize_risk_type(item.get('risk_type'))}：{str(item.get('summary') or item.get('evidence') or '')[:90]}"
            for item in related_items[:3]
        ]
        if not key_drivers:
            key_drivers = ["今日新闻库未发现直接命中该资产的高风险事件。"]

        reports.append(
            {
                "asset_symbol": symbol,
                "asset_name": base,
                "is_holding": bool(asset.get("is_holding")),
                "exposure_label": _asset_exposure_label(asset),
                "exposure_mode": str(asset.get("exposure_mode") or "bucket"),
                "exposure_bucket": str(asset.get("exposure_bucket") or "none"),
                "market_value": float(asset.get("market_value") or 0),
                "price_change_24h": float(asset.get("price_change_24h") or 0),
                "alert_threshold": int(asset.get("alert_threshold") or 70),
                "personal_risk_score": score,
                "risk_level": _risk_level_from_score(score),
                "summary": (
                    f"{base} 今日命中 {len(related_items)} 个相关风险事件，主要风险集中在 {'、'.join(risk_types[:3]) or '综合风险'}。"
                    if related_items
                    else f"{base} 今日暂无直接命中事件，当前风险以持仓/关注监控为主。"
                ),
                "risk_types": risk_types,
                "key_drivers": key_drivers,
                "evidence_summary": evidence_summary,
                "monitoring_items": [
                    f"{base} 官方公告与交易所充提状态",
                    f"{base} 链上大额转账和交易所流入",
                    f"{base} 价格、成交量和相关社群舆情变化",
                ],
                "actions": _fallback_asset_actions(asset, related_items, score),
                "source_event_count": len(related_items),
                "source_news_ids": [str(item.get("news_id") or "") for item in related_items if item.get("news_id")],
            }
        )

    return reports


def _merge_llm_asset_reports(llm_items: object, fallback_reports: list[dict[str, object]]) -> list[dict[str, object]]:
    if not isinstance(llm_items, list):
        return fallback_reports

    llm_by_symbol = {
        str(item.get("asset_symbol") or "").upper(): item
        for item in llm_items
        if isinstance(item, dict)
    }
    merged = []
    for fallback in fallback_reports:
        symbol = str(fallback.get("asset_symbol") or "").upper()
        llm_item = llm_by_symbol.get(symbol, {})
        merged.append(
            {
                **fallback,
                "summary": str(llm_item.get("summary") or fallback.get("summary")),
                "key_drivers": [
                    str(item).strip()
                    for item in llm_item.get("key_drivers", fallback.get("key_drivers", []))
                    if str(item).strip()
                ][:5],
                "monitoring_items": [
                    str(item).strip()
                    for item in llm_item.get("monitoring_items", fallback.get("monitoring_items", []))
                    if str(item).strip()
                ][:5],
                "actions": _sanitize_actions(llm_item.get("actions")) or fallback.get("actions", []),
            }
        )
    return merged


def _watch_coins(news_items: list[dict[str, object]], coin_items: list[dict[str, object]]) -> list[dict[str, object]]:
    if coin_items:
        return [
            {
                "symbol": str(item.get("symbol") or ""),
                "name": str(item.get("name") or item.get("symbol") or ""),
                "score": _clamp_score(item.get("final_score")),
                "level": str(item.get("risk_level") or _risk_level_from_score(_clamp_score(item.get("final_score")))),
                "news_count": int(item.get("news_count") or 0),
                "risk_type": str(item.get("main_risk_type") or "综合风险"),
            }
            for item in coin_items[:5]
        ]

    grouped: dict[str, dict[str, object]] = {}
    for item in news_items:
        for coin in item.get("coins", []):
            symbol = str(coin or "").strip()
            if not symbol or symbol == "--":
                continue
            current = grouped.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": symbol,
                    "score": 0,
                    "level": "低风险",
                    "news_count": 0,
                    "risk_type": _normalize_risk_type(item.get("risk_type")),
                },
            )
            score = max(int(current["score"]), _clamp_score(item.get("risk_score")))
            current["score"] = score
            current["level"] = _risk_level_from_score(score)
            current["news_count"] = int(current["news_count"]) + 1
            current["risk_type"] = _normalize_risk_type(item.get("risk_type"))

    return sorted(grouped.values(), key=lambda item: (int(item["score"]), int(item["news_count"])), reverse=True)[:5]


def _personal_watch_coins(user_assets: list[dict[str, object]], key_news: list[dict[str, object]]) -> list[dict[str, object]]:
    news_by_asset: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in key_news:
        for asset in item.get("matched_assets", []):
            news_by_asset[str(asset).upper()].append(item)

    output = []
    for asset in user_assets:
        base = str(asset.get("base_asset") or _base_asset(asset.get("symbol"))).upper()
        related_news = news_by_asset.get(base, [])
        max_personal_score = max((_clamp_score(item.get("personal_score")) for item in related_news), default=_clamp_score(asset.get("existing_risk_score")))
        output.append(
            {
                "symbol": str(asset.get("symbol") or base),
                "name": base,
                "score": max_personal_score,
                "level": _risk_level_from_score(max_personal_score),
                "news_count": len(related_news),
                "risk_type": str(related_news[0].get("risk_type") if related_news else asset.get("ai_summary") or "暂无直接命中事件"),
                "is_holding": bool(asset.get("is_holding")),
                "exposure_mode": str(asset.get("exposure_mode") or "bucket"),
                "exposure_bucket": str(asset.get("exposure_bucket") or "none"),
                "market_value": float(asset.get("market_value") or 0),
                "price_change_24h": float(asset.get("price_change_24h") or 0),
                "alert_threshold": int(asset.get("alert_threshold") or 70),
            }
        )

    return sorted(output, key=lambda item: (int(item["score"]), int(item["news_count"])), reverse=True)[:8]


def _fallback_actions(alert_level: str, red_count: int, high_count: int, watch_coins: list[dict[str, object]]) -> list[str]:
    actions = [
        "优先核验红色预警事件的官方公告、交易所状态页与链上地址证据。",
        "对重点资产设置价格、提现、链上大额转账和社群舆情的连续监控。",
        "避免依据单条未证实消息做方向性操作，等待多源证据交叉确认。",
    ]
    if red_count > 0 or "红" in alert_level:
        actions.insert(0, "短期内降低对红色预警相关资产的新增暴露，先确认资金可用性和平台提现状态。")
    elif high_count > 0:
        actions.insert(0, "将高风险新闻加入观察清单，关注 24 小时内是否出现连续同类事件。")
    if watch_coins:
        symbols = "、".join(str(item.get("symbol") or "") for item in watch_coins[:3] if item.get("symbol"))
        if symbols:
            actions.append(f"重点复核 {symbols} 的相关新闻和持仓暴露。")
    return actions


def load_user_profile_node(state: DailyReportState) -> DailyReportState:
    user_id = str(state.get("user_id") or DEFAULT_USER_ID)
    errors = list(state.get("errors", []))
    try:
        watchlist = [_asset_profile_item(item) for item in list_user_assets(user_id)]
    except Exception as exc:
        watchlist = []
        errors.append(f"load_user_watchlist_failed: {exc}")

    try:
        favorite_news = [_favorite_brief(item) for item in list_favorites(user_id, "news")] if user_id != DEFAULT_USER_ID else []
    except Exception as exc:
        favorite_news = []
        errors.append(f"load_user_favorites_failed: {exc}")

    holding_assets = [item for item in watchlist if item.get("is_holding")]
    profile = {
        "user_id": user_id,
        "display_name": str(state.get("user_display_name") or ("Demo 用户" if user_id == DEFAULT_USER_ID else "当前用户")),
        "profile_source": "anonymous_demo" if user_id == DEFAULT_USER_ID else "authenticated",
        "assets": watchlist,
        "asset_count": len(watchlist),
        "holding_count": len(holding_assets),
        "favorite_news": favorite_news[:10],
        "favorite_news_count": len(favorite_news),
        "has_personal_assets": bool(watchlist),
    }
    return {**state, "user_id": user_id, "user_profile": profile, "errors": errors}


def load_daily_source_node(state: DailyReportState) -> DailyReportState:
    date_filter = str(state.get("date_filter") or "24h")
    errors = list(state.get("errors", []))
    try:
        news_response = run_ranking_agent("news", date_filter=date_filter, limit=0, score_missing=False)
        coin_response = run_ranking_agent("coins", date_filter=date_filter, limit=0, score_missing=False)
        return {
            **state,
            "date_filter": date_filter,
            "range": "7d" if date_filter == "7d" else "24h",
            "news_items": list(news_response.get("items") or []),
            "coin_items": list(coin_response.get("items") or []),
            "errors": errors,
        }
    except Exception as exc:
        return {
            **state,
            "date_filter": date_filter,
            "range": "7d" if date_filter == "7d" else "24h",
            "news_items": [],
            "coin_items": [],
            "errors": errors + [f"load_daily_source_failed: {exc}"],
        }


def aggregate_daily_signals_node(state: DailyReportState) -> DailyReportState:
    news_items = list(state.get("news_items", []))
    user_profile = dict(state.get("user_profile") or {})
    user_assets = list(user_profile.get("assets") or [])
    scores = [_clamp_score(item.get("risk_score")) for item in news_items]
    average_score = round(sum(scores) / len(scores)) if scores else 0
    high_count = sum(1 for item in news_items if _is_high_risk_news(item))
    red_count = sum(1 for item in news_items if _is_red_alert_news(item))
    has_personal_assets = bool(user_assets)
    personal_news = _key_news(news_items, user_assets, limit=50) if has_personal_assets else []
    top_news = personal_news[:5]
    asset_reports = _asset_reports_from_profile(user_assets, personal_news) if has_personal_assets else []
    personal_scores = [
        *[_clamp_score(item.get("personal_score")) for item in personal_news],
        *[_clamp_score(item.get("personal_risk_score")) for item in asset_reports],
    ]
    personal_risk_score = max(personal_scores, default=0)
    personal_high_count = sum(1 for item in personal_news if _clamp_score(item.get("personal_score")) >= 80)
    personal_red_count = sum(1 for item in personal_news if _clamp_score(item.get("personal_score")) >= 90)
    alert_level = (
        "红色预警"
        if personal_red_count
        else "高风险"
        if personal_high_count
        else "中风险"
        if personal_risk_score >= 55
        else "低风险"
    )
    risk_types = _risk_type_stats(personal_news)
    risk_themes = _risk_themes_from_key_news(personal_news)
    watch_coins = _personal_watch_coins(user_assets, personal_news) if has_personal_assets else []
    affected_assets = sorted({asset for item in personal_news for asset in item.get("matched_assets", [])})
    latest_time = max(
        [str(item.get("published_at") or item.get("date") or "") for item in news_items if item.get("published_at") or item.get("date")],
        default="",
    )
    fallback_actions = (
        _fallback_actions(alert_level, personal_red_count, personal_high_count, watch_coins)
        if has_personal_assets
        else ["先在我的风险资产中添加关注币种或持仓信息，再生成个人风险日报。"]
    )

    signals = {
        "range": state.get("range") or "24h",
        "generated_at": latest_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "news_count": len(news_items),
        "user_profile": user_profile,
        "user_assets_count": len(user_assets),
        "holding_assets_count": int(user_profile.get("holding_count") or 0),
        "favorite_news_count": int(user_profile.get("favorite_news_count") or 0),
        "average_score": average_score,
        "personal_risk_score": personal_risk_score,
        "high_count": high_count,
        "red_count": red_count,
        "personal_high_count": personal_high_count,
        "personal_red_count": personal_red_count,
        "alert_level": alert_level,
        "top_risk_type": str(risk_types[0]["name"]) if risk_types else "综合风险",
        "top_coin": str(watch_coins[0]["symbol"]) if watch_coins else "",
        "key_news": top_news,
        "personal_news_count": len(personal_news),
        "asset_reports": asset_reports,
        "risk_themes": risk_themes,
        "risk_types": risk_types,
        "watch_coins": watch_coins,
        "affected_assets": affected_assets,
        "risk_type_counts": dict(Counter(_normalize_risk_type(item.get("risk_type")) for item in personal_news)),
        "fallback_actions": fallback_actions,
    }
    return {**state, "signals": signals}


def llm_daily_writer_node(state: DailyReportState) -> DailyReportState:
    signals = dict(state.get("signals") or {})
    if int(signals.get("user_assets_count") or 0) == 0:
        return {**state, "llm_draft": {"source": "rule_fallback"}}
    prompt = f"""
你是 CryptoRisk 的加密货币金融风控日报 Agent。请基于已有新闻风险标注数据和用户关注/持仓资产，生成个性化风险日报。

要求：
1. 只输出 JSON，不要 Markdown。
2. 不得给出买入、卖出、做空、梭哈等交易方向建议。
3. 必须围绕用户资产说清楚：哪些事件命中用户资产、为什么相关、风险强度、需要核验证据、接下来 24 小时盯什么。
4. 用户关注/持仓了什么资产，日报里才允许出现什么资产；不得新增未关注资产。
5. 如果用户没有关注资产，要提醒先添加关注资产，不要生成全市场资产列表。
6. 输出字段：
{{
  "headline": "一句话标题",
  "summary": "120-180 字中文个性化日报摘要",
  "market_mood": "risk_off / neutral / risk_on",
  "risk_themes": [
    {{
      "title": "聚合风险主题标题，不要照抄新闻标题",
      "summary": "聚合分析，不逐条列新闻",
      "severity_reason": "为什么这个主题对用户资产重要",
      "monitoring_items": ["接下来24小时监控项"]
    }}
  ],
  "asset_reports": [
    {{
      "asset_symbol": "必须来自 user_profile.assets 的 symbol",
      "summary": "该资产的今日聚合风险判断，不逐条列新闻",
      "key_drivers": ["聚合后的风险驱动，不照抄新闻标题"],
      "monitoring_items": ["接下来24小时监控项"],
      "actions": ["不含交易方向的处置建议"]
    }}
  ],
  "focus_points": ["与用户资产直接相关的关注点"],
  "user_actions": ["用户处置建议"],
  "impact_summary": "对用户关注资产/持仓组合的影响分析",
  "source": "llm"
}}

已有结构化信号：
{json.dumps(signals, ensure_ascii=False)}
"""
    llm_result = call_llm_json(prompt, temperature=0.1)
    if llm_result.get("_llm_error"):
        return {
            **state,
            "llm_draft": {"source": "rule_fallback", "error": str(llm_result.get("_llm_error"))},
            "errors": list(state.get("errors", [])) + [f"llm_daily_writer_failed: {llm_result.get('_llm_error')}"],
        }
    return {**state, "llm_draft": llm_result}


def finalize_daily_report_node(state: DailyReportState) -> DailyReportState:
    signals = dict(state.get("signals") or {})
    draft = dict(state.get("llm_draft") or {})
    user_profile = dict(signals.get("user_profile") or state.get("user_profile") or {})
    key_news = list(signals.get("key_news") or [])
    fallback_themes = list(signals.get("risk_themes") or [])
    risk_themes = _merge_llm_risk_themes(draft.get("risk_themes"), fallback_themes)
    fallback_asset_reports = list(signals.get("asset_reports") or [])
    asset_reports = _merge_llm_asset_reports(draft.get("asset_reports"), fallback_asset_reports)
    risk_types = list(signals.get("risk_types") or [])
    watch_coins = list(signals.get("watch_coins") or [])
    user_assets_count = int(signals.get("user_assets_count") or 0)
    alert_level = str(signals.get("alert_level") or "低风险")
    top_type = str(signals.get("top_risk_type") or "综合风险")
    top_coin = str(signals.get("top_coin") or "")
    fallback_headline = (
        "请先添加关注资产，以生成个人风险日报"
        if user_assets_count == 0
        else f"你的 {top_coin} 等资产今日需关注 {top_type}"
        if key_news and top_coin
        else f"你的关注资产今日需关注 {top_type}"
        if key_news
        else "你的关注资产暂无直接高风险命中"
    )

    fallback_summary = (
        f"你当前关注 {user_assets_count} 个资产，日报命中 {len(key_news)} 条相关风险事件，"
        f"个人风险分 {signals.get('personal_risk_score', 0)}。最高相关事件为「{key_news[0].get('title')}」，"
        f"影响资产 { '、'.join([str(asset) for asset in key_news[0].get('matched_assets', [])]) or top_coin or '待确认'}，"
        f"风险类型为 {key_news[0].get('risk_type')}。"
        if key_news
        else "当前还没有关注资产。请先在我的风险资产中添加关注币种或持仓权重，系统会生成更准确的个人风险日报。"
        if user_assets_count == 0
        else f"你当前关注 {user_assets_count} 个资产，本期新闻库未命中这些资产的直接高风险事件。建议继续关注公告、提现状态和链上大额转账变化。"
    )
    actions = (
        list(signals.get("fallback_actions") or [])
        if user_assets_count == 0
        else _sanitize_actions(draft.get("user_actions")) or list(signals.get("fallback_actions") or [])
    )
    focus_points = [
        str(item).strip()
        for item in draft.get("focus_points", [])
        if str(item).strip()
    ][:6] if isinstance(draft.get("focus_points"), list) else []
    if user_assets_count == 0:
        focus_points = []
    fallback_impact_summary = (
        "当前没有关注资产。添加资产后，系统会只围绕你的关注/持仓资产聚合今日新闻并生成分项报告。"
        if user_assets_count == 0
        else f"本期共生成 {len(asset_reports)} 个资产分项报告，命中 {signals.get('personal_news_count', len(key_news))} 条与用户资产相关的风险新闻。"
        if key_news
        else f"本期共生成 {len(asset_reports)} 个资产分项报告，新闻库暂未命中直接相关风险事件，建议继续监控公告、交易所状态和链上异常。"
    )
    headline = fallback_headline if user_assets_count == 0 else str(draft.get("headline") or fallback_headline)
    summary = fallback_summary if user_assets_count == 0 else str(draft.get("summary") or fallback_summary)
    impact_summary = fallback_impact_summary if user_assets_count == 0 else str(draft.get("impact_summary") or fallback_impact_summary)

    report = {
        "date": state.get("date_filter") or "24h",
        "range": state.get("range") or "24h",
        "generated_at": signals.get("generated_at", ""),
        "source": draft.get("source") if draft.get("source") == "llm" else "rule_fallback",
        "user_id": state.get("user_id") or DEFAULT_USER_ID,
        "user_profile": user_profile,
        "user_assets_count": user_assets_count,
        "holding_assets_count": int(signals.get("holding_assets_count") or 0),
        "favorite_news_count": int(signals.get("favorite_news_count") or 0),
        "affected_assets": list(signals.get("affected_assets") or []),
        "personal_risk_score": int(signals.get("personal_risk_score") or 0),
        "personal_high_count": int(signals.get("personal_high_count") or 0),
        "personal_red_count": int(signals.get("personal_red_count") or 0),
        "headline": headline,
        "summary": summary,
        "alert_level": alert_level,
        "market_mood": str(draft.get("market_mood") or ("risk_off" if alert_level in {"红色预警", "高风险"} else "neutral")),
        "news_count": int(signals.get("news_count") or 0),
        "average_score": int(signals.get("average_score") or 0),
        "high_count": int(signals.get("high_count") or 0),
        "red_count": int(signals.get("red_count") or 0),
        "key_news": key_news,
        "asset_reports": asset_reports,
        "risk_themes": risk_themes,
        "risk_types": risk_types,
        "watch_coins": watch_coins,
        "focus_points": focus_points,
        "actions": actions,
        "impact_summary": impact_summary,
        "errors": list(state.get("errors", [])),
    }
    return {**state, "report": report}
