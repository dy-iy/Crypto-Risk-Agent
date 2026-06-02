from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas_portfolio import (
    ExposureSource,
    EventAssetRelation,
    PortfolioImpactAsset,
    PortfolioImpactEvent,
    PortfolioImpactResponse,
    PortfolioWatchlistItem,
)
from app.services.coin_extraction_service import COIN_DICTIONARY, extract_coins_from_text
from app.services.data_loader import load_scored_news, shorten
from app.services.portfolio_service import (
    DEFAULT_USER_ID,
    _clamp_news_score,
    _load_state_unlocked,
    _normalize_symbol,
    _now,
    _save_state_unlocked,
    _state_lock,
    list_watchlist,
)
from app.services.ranking_aggregation_service import SOURCE_URL_FIELDS, first_text_value


DEFAULT_WINDOW_DAYS = 30
DEFAULT_TOP_N = 10
DEFAULT_PER_ASSET_LIMIT = 200
MIN_IMPACT_THRESHOLD = 1
EXPOSURE_BUCKET_PCT = {
    "none": 0.0,
    "low": 0.05,
    "medium": 0.15,
    "high": 0.30,
}

ECOSYSTEM_KEYWORDS: dict[str, list[str]] = {
    "BTCUSDT": ["BTC", "Bitcoin", "比特币", "ETF", "miner", "mining", "halving", "减半", "矿工"],
    "ETHUSDT": [
        "ETH",
        "Ethereum",
        "以太坊",
        "L2",
        "Arbitrum",
        "Optimism",
        "Base",
        "Uniswap",
        "Aave",
        "Lido",
        "EigenLayer",
    ],
    "SOLUSDT": ["SOL", "Solana", "Jupiter", "Jito", "Raydium", "Marinade", "Pyth", "Orca", "Pump.fun"],
    "BNBUSDT": ["BNB", "BNB Chain", "BSC", "Binance Smart Chain", "币安链"],
    "XRPUSDT": ["XRP", "Ripple", "瑞波"],
    "TONUSDT": ["TON", "Toncoin", "Telegram", "TON Chain"],
    "USDTUSDT": ["USDT", "Tether", "泰达", "稳定币", "脱锚"],
    "USDCUSDT": ["USDC", "Circle", "稳定币", "脱锚"],
}

NEGATIVE_TERMS = [
    "攻击",
    "漏洞",
    "被盗",
    "暂停",
    "提现",
    "脱锚",
    "清算",
    "下架",
    "调查",
    "诉讼",
    "制裁",
    "风险",
    "崩盘",
    "exploit",
    "hack",
    "attack",
    "lawsuit",
    "liquidation",
]
POSITIVE_TERMS = ["获批", "恢复", "合作", "上线", "增长", "流入", "approved", "partnership", "recovery"]


def calculate_portfolio_impact_score(input_data: dict[str, float | int]) -> int:
    event_risk_score = _clamp_impact_number(input_data.get("eventRiskScore", 0), 0, 100)
    asset_relation_score = _clamp_impact_number(input_data.get("assetRelationScore", 0), 0, 1)
    user_exposure_pct = _clamp_impact_number(input_data.get("userExposurePct", 0), 0, 1)
    time_decay_factor = _clamp_impact_number(input_data.get("timeDecayFactor", 1), 0, 1)
    urgency_score = _positive_factor(input_data.get("urgencyScore", 1))
    source_trust_score = _positive_factor(input_data.get("sourceTrustScore", 1))
    confidence_score = _positive_factor(input_data.get("confidenceScore", 1))
    market_anomaly_factor = _positive_factor(input_data.get("marketAnomalyFactor", 1))
    user_risk_preference_factor = _positive_factor(input_data.get("userRiskPreferenceFactor", 1))

    raw_score = (
        event_risk_score
        * asset_relation_score
        * _exposure_bucket_weight(user_exposure_pct)
        * time_decay_factor
        * urgency_score
        * source_trust_score
        * confidence_score
        * market_anomaly_factor
        * user_risk_preference_factor
    )
    return int(max(0, min(100, round(raw_score))))


def infer_event_asset_relations(event: dict[str, Any], target_symbols: set[str] | None = None) -> list[EventAssetRelation]:
    event_id = _event_id(event)
    title = str(event.get("title") or "")
    content = str(event.get("content") or event.get("summary") or "")
    text = f"{title}\n{content}\n{event.get('risk_type') or ''}"
    now = _now()
    candidates = sorted(target_symbols) if target_symbols else sorted(_known_relation_symbols(event))
    relations: list[EventAssetRelation] = []

    for symbol in candidates:
        normalized = _normalize_symbol(symbol)
        match = _match_asset_relation(normalized, event, text)
        if not match:
            continue
        relation_score, relation_type, reasons = match
        direction = _infer_direction(text)
        event_risk_score = _clamp_news_score(event.get("risk_score"))
        relations.append(
            EventAssetRelation(
                id=f"{event_id}:{normalized}",
                event_id=event_id,
                asset_symbol=normalized,
                relation_score=relation_score,
                relation_type=relation_type,
                direction=direction,
                base_asset_impact_score=round(event_risk_score * relation_score),
                reasons=reasons,
                metadata={"source": "keyword_mvp"},
                created_at=now,
                updated_at=now,
            )
        )
    return relations


def get_portfolio_impact_for_user(
    user_id: str = DEFAULT_USER_ID,
    window_days: int = DEFAULT_WINDOW_DAYS,
    top_n: int = DEFAULT_TOP_N,
    per_asset_limit: int = DEFAULT_PER_ASSET_LIMIT,
) -> PortfolioImpactResponse:
    safe_window_days = max(1, min(365, int(window_days or DEFAULT_WINDOW_DAYS)))
    safe_top_n = max(1, min(50, int(top_n or DEFAULT_TOP_N)))
    safe_per_asset_limit = max(10, min(500, int(per_asset_limit or DEFAULT_PER_ASSET_LIMIT)))
    watch_items = list_watchlist(user_id)
    exact_total_value = sum(item.market_value for item in watch_items if item.is_holding and item.market_value > 0)
    holdings = [
        item
        for item in watch_items
        if item.is_holding and resolve_user_exposure_pct(item, exact_total_value)[0] > 0
    ]
    generated_at = _now()
    if not holdings:
        return PortfolioImpactResponse(generatedAt=generated_at, windowDays=safe_window_days)

    holding_symbols = {item.symbol for item in holdings}
    relations_by_symbol = _load_recent_relations_by_symbol(holding_symbols, safe_window_days)
    missing_symbols = {symbol for symbol in holding_symbols if symbol not in relations_by_symbol or not relations_by_symbol[symbol]}
    if missing_symbols:
        _sync_event_asset_relations(missing_symbols, safe_window_days)
        relations_by_symbol = _load_recent_relations_by_symbol(holding_symbols, safe_window_days)

    news_by_id = {_event_id(item): item for item in load_scored_news() if isinstance(item, dict)}
    cache_updates: dict[str, Any] = {}
    asset_results: list[PortfolioImpactAsset] = []
    all_events: list[PortfolioImpactEvent] = []

    for holding in holdings:
        exposure_pct, exposure_source = resolve_user_exposure_pct(holding, exact_total_value)
        top_events: list[PortfolioImpactEvent] = []
        relations = relations_by_symbol.get(holding.symbol, [])[:safe_per_asset_limit]
        for relation in relations:
            event = news_by_id.get(relation.event_id)
            if not event:
                continue
            impact_event = _build_impact_event(event, relation, holding, exposure_pct, exposure_source, safe_window_days)
            if impact_event.portfolioImpactScore < MIN_IMPACT_THRESHOLD:
                continue
            top_events.append(impact_event)
            cache_updates[f"{user_id}:{holding.symbol}:{relation.event_id}"] = {
                "impact_score": impact_event.portfolioImpactScore,
                "reasons": impact_event.reasons,
                "calculated_at": generated_at,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
            }

        top_events = sorted(top_events, key=lambda item: item.portfolioImpactScore, reverse=True)[:safe_top_n]
        all_events.extend(top_events)
        asset_results.append(
            PortfolioImpactAsset(
                assetSymbol=holding.symbol,
                holdingPct=round(exposure_pct, 4),
                exposureSource=exposure_source,
                marketValue=round(holding.market_value, 6),
                topEvents=top_events,
            )
        )

    _write_impact_cache(cache_updates)
    all_events = sorted(all_events, key=lambda item: item.portfolioImpactScore, reverse=True)
    portfolio_impact_score = all_events[0].portfolioImpactScore if all_events else 0
    return PortfolioImpactResponse(
        portfolioImpactScore=portfolio_impact_score,
        assets=asset_results,
        generatedAt=generated_at,
        windowDays=safe_window_days,
    )


def _build_impact_event(
    event: dict[str, Any],
    relation: EventAssetRelation,
    holding: PortfolioWatchlistItem,
    exposure_pct: float,
    exposure_source: ExposureSource,
    window_days: int,
) -> PortfolioImpactEvent:
    event_risk_score = _clamp_news_score(event.get("risk_score"))
    confidence_score = max(0.5, min(1, relation.relation_score))
    time_decay_factor = _time_decay_factor(str(event.get("published_at") or event.get("date") or ""), window_days)
    urgency_score = 1.08 if event_risk_score >= 85 else 1
    source_trust_score = 1 if first_text_value(event, SOURCE_URL_FIELDS) else 0.92
    market_anomaly_factor = 1.08 if abs(holding.price_change_24h) >= 0.05 else 1
    impact_score = calculate_portfolio_impact_score(
        {
            "eventRiskScore": event_risk_score,
            "assetRelationScore": relation.relation_score,
            "userExposurePct": exposure_pct,
            "timeDecayFactor": time_decay_factor,
            "urgencyScore": urgency_score,
            "sourceTrustScore": source_trust_score,
            "confidenceScore": confidence_score,
            "marketAnomalyFactor": market_anomaly_factor,
            "userRiskPreferenceFactor": 1,
        }
    )
    reasons = [
        *relation.reasons[:2],
        f"你当前持有 {holding.symbol}，仓位占组合 {round(exposure_pct * 100, 2)}%",
        f"事件风险分为 {event_risk_score}/100",
        f"时间衰减因子 {round(time_decay_factor, 2)}",
    ]
    if source_trust_score >= 1:
        reasons.append("来源可信度按默认高可信处理")
    if market_anomaly_factor > 1:
        reasons.append("当前价格波动较大，市场异常因子上调")

    return PortfolioImpactEvent(
        eventId=relation.event_id,
        title=str(event.get("title") or ""),
        summary=str(event.get("summary") or shorten(str(event.get("content") or ""), 160)),
        publishedAt=str(event.get("published_at") or event.get("date") or ""),
        eventRiskScore=event_risk_score,
        assetRelationScore=round(relation.relation_score, 3),
        userExposurePct=round(exposure_pct, 4),
        timeDecayFactor=round(time_decay_factor, 3),
        urgencyScore=round(urgency_score, 3),
        sourceTrustScore=round(source_trust_score, 3),
        confidenceScore=round(confidence_score, 3),
        marketAnomalyFactor=round(market_anomaly_factor, 3),
        userRiskPreferenceFactor=1,
        exposureSource=exposure_source,
        portfolioImpactScore=impact_score,
        direction=relation.direction,
        relationType=relation.relation_type,
        riskType=str(event.get("risk_type") or ""),
        sourceUrl=first_text_value(event, SOURCE_URL_FIELDS),
        reasons=reasons,
    )


def get_estimated_exposure_pct_from_bucket(bucket: str) -> float:
    return EXPOSURE_BUCKET_PCT.get(bucket, 0.0)


def get_exposure_bucket_weight(pct: float) -> float:
    return _exposure_bucket_weight(pct)


def resolve_user_exposure_pct(
    holding: PortfolioWatchlistItem,
    portfolio_total_value: float = 0,
) -> tuple[float, ExposureSource]:
    custom_pct = holding.custom_exposure_pct
    if custom_pct is not None and custom_pct > 0:
        return min(1, max(0, float(custom_pct))), "custom"
    if holding.amount > 0 and holding.current_price > 0 and portfolio_total_value > 0:
        return min(1, max(0, holding.market_value / portfolio_total_value)), "exact"
    bucket_pct = get_estimated_exposure_pct_from_bucket(holding.exposure_bucket)
    if bucket_pct > 0:
        return bucket_pct, "bucket"
    return 0.0, "unknown"


def _sync_event_asset_relations(target_symbols: set[str], window_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    target_symbols = {_normalize_symbol(symbol) for symbol in target_symbols}
    updates: dict[str, EventAssetRelation] = {}
    for event in load_scored_news():
        if not isinstance(event, dict) or _event_time(event) < cutoff:
            continue
        for relation in infer_event_asset_relations(event, target_symbols):
            updates[relation.id] = relation
    if not updates:
        return
    with _state_lock:
        state = _load_state_unlocked()
        existing = {
            str(item.get("id")): item
            for item in state.get("event_asset_relations", [])
            if isinstance(item, dict)
        }
        for relation_id, relation in updates.items():
            previous = existing.get(relation_id)
            if previous and previous.get("created_at"):
                relation.created_at = str(previous["created_at"])
            existing[relation_id] = relation.model_dump()
        state["event_asset_relations"] = list(existing.values())
        _save_state_unlocked(state)


def _load_recent_relations_by_symbol(symbols: set[str], window_days: int) -> dict[str, list[EventAssetRelation]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    news_by_id = {_event_id(item): item for item in load_scored_news() if isinstance(item, dict)}
    grouped: dict[str, list[EventAssetRelation]] = {symbol: [] for symbol in symbols}
    with _state_lock:
        state = _load_state_unlocked()
        raw_relations = list(state.get("event_asset_relations", []))
    for raw in raw_relations:
        if not isinstance(raw, dict):
            continue
        try:
            relation = EventAssetRelation.model_validate(raw)
        except Exception:
            continue
        if relation.asset_symbol not in symbols:
            continue
        event = news_by_id.get(relation.event_id)
        if not event or _event_time(event) < cutoff:
            continue
        grouped.setdefault(relation.asset_symbol, []).append(relation)
    for symbol, relations in grouped.items():
        grouped[symbol] = sorted(
            relations,
            key=lambda relation: (
                relation.base_asset_impact_score or 0,
                relation.relation_score,
                str(news_by_id.get(relation.event_id, {}).get("published_at") or ""),
            ),
            reverse=True,
        )
    return grouped


def _write_impact_cache(updates: dict[str, Any]) -> None:
    if not updates:
        return
    # TODO: Replace this local JSON cache with an indexed table when portfolio_state moves to a database.
    with _state_lock:
        state = _load_state_unlocked()
        cache = state.setdefault("portfolio_impact_cache", {})
        cache.update(updates)
        _save_state_unlocked(state)


def _match_asset_relation(symbol: str, event: dict[str, Any], text: str) -> tuple[float, str, list[str]] | None:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    upper_text = text.upper()
    raw_coins = event.get("coins")
    if isinstance(raw_coins, list) and any(str(coin).upper() in {base, symbol} for coin in raw_coins):
        return 0.92, "direct_mention", [f"事件币种字段直接包含 {base}"]

    raw_details = event.get("coin_details")
    if isinstance(raw_details, list):
        for detail in raw_details:
            if isinstance(detail, dict) and str(detail.get("symbol") or "").upper() in {base, symbol}:
                return 0.95, "direct_mention", [f"事件实体识别直接命中 {base}"]

    terms = _asset_terms(symbol)
    matched_terms = [term for term in terms if _term_in_text(term, text, upper_text)]
    if not matched_terms:
        matches = extract_coins_from_text(str(event.get("title") or ""), str(event.get("content") or ""))
        matched_terms = [
            term
            for match in matches
            if str(match.get("symbol") or "").upper() == base
            for term in match.get("matched_terms", [])[:3]
        ]
    if not matched_terms:
        return None

    relation_type = _infer_relation_type(text)
    score = 0.86 if base in {term.upper() for term in matched_terms} or symbol in {term.upper() for term in matched_terms} else 0.72
    if relation_type in {"security_incident", "regulatory", "exchange"}:
        score = min(0.95, score + 0.08)
    return score, relation_type, [f"关键词关联 {symbol}: {', '.join(matched_terms[:4])}"]


def _asset_terms(symbol: str) -> list[str]:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    terms = [symbol, base, *ECOSYSTEM_KEYWORDS.get(symbol, [])]
    dictionary_terms = COIN_DICTIONARY.get(base, {}).get("terms", [])
    terms.extend(str(term) for term in dictionary_terms)
    return list(dict.fromkeys(term for term in terms if term))


def _known_relation_symbols(event: dict[str, Any]) -> set[str]:
    symbols: set[str] = set(ECOSYSTEM_KEYWORDS)
    raw_coins = event.get("coins")
    if isinstance(raw_coins, list):
        for coin in raw_coins:
            try:
                symbols.add(_normalize_symbol(str(coin)))
            except Exception:
                continue
    return symbols


def _infer_relation_type(text: str) -> str:
    if re.search(r"攻击|漏洞|被盗|exploit|hack|attack", text, re.I):
        return "security_incident"
    if re.search(r"监管|SEC|法院|诉讼|政策|制裁|regulatory|lawsuit", text, re.I):
        return "regulatory"
    if re.search(r"交易所|提现|下架|Binance|Coinbase|OKX|exchange", text, re.I):
        return "exchange"
    if re.search(r"生态|协议|DeFi|L2|protocol|ecosystem", text, re.I):
        return "ecosystem_protocol"
    if re.search(r"宏观|美联储|利率|美元|macro|fed", text, re.I):
        return "macro"
    return "direct_mention"


def _infer_direction(text: str) -> str:
    lowered = text.lower()
    if any(term.lower() in lowered for term in NEGATIVE_TERMS):
        return "negative"
    if any(term.lower() in lowered for term in POSITIVE_TERMS):
        return "positive"
    return "neutral"


def _time_decay_factor(value: str, window_days: int) -> float:
    event_time = _parse_event_time(value)
    if not event_time:
        return 0.72
    age_days = max(0, (datetime.now(timezone.utc) - event_time).total_seconds() / 86400)
    if age_days >= window_days:
        return 0
    # Smooth enough for recent events while still reducing older items.
    return max(0.25, min(1, math.exp(-age_days / max(1, window_days * 0.65))))


def _event_time(event: dict[str, Any]) -> datetime:
    return _parse_event_time(str(event.get("published_at") or event.get("date") or "")) or datetime.now(timezone.utc)


def _parse_event_time(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for candidate in [text, text.replace("/", "-"), text.replace(" ", "T")]:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("news_id") or event.get("id") or event.get("csv_order") or uuid.uuid4().hex)


def _term_in_text(term: str, text: str, upper_text: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    return term.upper() in upper_text


def _exposure_bucket_weight(user_exposure_pct: float) -> float:
    if user_exposure_pct <= 0:
        return 0
    if user_exposure_pct <= 0.05:
        return 0.3
    if user_exposure_pct <= 0.15:
        return 0.6
    if user_exposure_pct <= 0.30:
        return 0.85
    return 1.0


def _positive_factor(value: float | int | None) -> float:
    return max(0, float(value if value is not None else 1))


def _clamp_impact_number(value: float | int | None, minimum: float, maximum: float) -> float:
    try:
        number = float(value if value is not None else minimum)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(maximum, number))
