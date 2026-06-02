#!/usr/bin/env python3
"""Call the CryptoRisk API for OpenClaw/ArkClaw skills."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "https://kassa-wiki.top"
DEFAULT_TIMEOUT_SECONDS = 90


def api_base() -> str:
    return os.environ.get("CRYPTO_RISK_API_BASE", DEFAULT_BASE_URL).rstrip("/")


def api_timeout() -> float:
    raw = os.environ.get("CRYPTO_RISK_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(DEFAULT_TIMEOUT_SECONDS)


def request_json(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    url = f"{api_base()}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=api_timeout()) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Cannot reach {url}: {exc.reason}") from exc


def query(params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return urllib.parse.urlencode(clean)


def emit(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(payload))


def to_markdown(payload: Any) -> str:
    if isinstance(payload, dict) and payload.get("status") == "ok" and set(payload) == {"status"}:
        return "Health: ok"
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
        return format_report(payload["data"])
    if isinstance(payload, dict) and payload.get("ranking_type") == "news":
        return format_news_list(payload.get("items", []), payload.get("date"))
    if isinstance(payload, dict) and payload.get("ranking_type") == "coin":
        return format_coin_list(payload.get("items", []), payload.get("date"))
    if isinstance(payload, dict) and "answer" in payload:
        return str(payload.get("answer") or "")
    if isinstance(payload, dict) and {"total_news", "high_risk_news"} & set(payload):
        return format_overview(payload)
    if isinstance(payload, dict) and {"title", "risk_score"} & set(payload):
        return format_news_item(payload)
    if isinstance(payload, dict) and {"symbol", "final_score"} & set(payload):
        return format_coin_item(payload)
    if isinstance(payload, dict) and "job_id" in payload:
        return format_job(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def risk_score(report: dict[str, Any]) -> Any:
    return report.get("final_risk_score") or report.get("risk_score") or 0


def number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"Summary: {report.get('summary', '')}",
        f"Risk: {report.get('risk_level', '')} / {risk_score(report)}",
        f"Confidence: {report.get('confidence_level', '')}",
    ]
    categories = report.get("risk_categories") or []
    if categories:
        lines.append(f"Categories: {', '.join(map(str, categories))}")
    signals = report.get("risk_signals") or []
    if signals:
        lines.append("Signals:")
        lines.extend(f"- {item}" for item in signals[:8])
    evidence = report.get("evidence") or report.get("evidence_items") or []
    if evidence:
        lines.append("Evidence:")
        for item in evidence[:8]:
            if isinstance(item, dict):
                text = item.get("evidence_text") or item.get("text") or item.get("supports") or ""
                explanation = item.get("explanation") or item.get("signal_type") or ""
                lines.append(f"- {text} {f'({explanation})' if explanation else ''}".strip())
            else:
                lines.append(f"- {item}")
    impact = report.get("impact") or []
    if impact:
        lines.append("Impact:")
        lines.extend(f"- {item}" for item in impact[:8])
    advice = report.get("advice") or []
    if advice:
        lines.append("Advice:")
        lines.extend(f"- {item}" for item in advice[:8])
    return "\n".join(lines)


def format_news_item(item: dict[str, Any]) -> str:
    coins = item.get("coins") or []
    lines = [
        f"#{item.get('rank', '-')} {item.get('title', '')}",
        f"Risk: {item.get('risk_level', '')} / {item.get('risk_score', '')}",
        f"Type: {item.get('risk_type', '')}",
        f"Published: {item.get('published_at') or item.get('date') or ''}",
    ]
    if coins:
        lines.append(f"Coins: {', '.join(map(str, coins))}")
    if item.get("summary"):
        lines.append(f"Summary: {item.get('summary')}")
    if item.get("evidence"):
        lines.append(f"Evidence: {item.get('evidence')}")
    if item.get("source_url"):
        lines.append(f"Source: {item.get('source_url')}")
    return "\n".join(lines)


def format_news_list(items: list[Any], date: Any = None) -> str:
    lines = [f"News ranking ({date or 'default'}):"]
    for item in items:
        if not isinstance(item, dict):
            continue
        coins = ", ".join(map(str, item.get("coins") or []))
        suffix = f" [{coins}]" if coins else ""
        lines.append(
            f"{item.get('rank', '-')}. {item.get('title', '')} - "
            f"{item.get('risk_level', '')} {item.get('risk_score', '')}{suffix}"
        )
    return "\n".join(lines)


def format_coin_item(item: dict[str, Any]) -> str:
    lines = [
        f"{item.get('symbol', '')} {item.get('name', '')}".strip(),
        f"Risk: {item.get('risk_level', '')} / {item.get('final_score', '')}",
        f"Main type: {item.get('main_risk_type', '')}",
        f"News count: {item.get('news_count', '')}",
    ]
    if item.get("top_news_title"):
        lines.append(f"Top news: {item.get('top_news_title')}")
    if item.get("summary"):
        lines.append(f"Summary: {item.get('summary')}")
    related = item.get("related_news") or []
    if related:
        lines.append("Related news:")
        for news in related[:8]:
            if isinstance(news, dict):
                lines.append(
                    f"- {news.get('title', '')} "
                    f"({news.get('risk_level', '')} {news.get('risk_score', '')})"
                )
    return "\n".join(lines)


def format_coin_list(items: list[Any], date: Any = None) -> str:
    lines = [f"Coin ranking ({date or 'default'}):"]
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"{item.get('rank', '-')}. {item.get('symbol', '')} - "
            f"{item.get('risk_level', '')} {item.get('final_score', '')}; "
            f"{item.get('main_risk_type', '')}; news={item.get('news_count', '')}"
        )
    return "\n".join(lines)


def format_overview(payload: dict[str, Any]) -> str:
    lines = [
        f"Overview: {payload.get('date', '')}",
        f"Total news: {payload.get('total_news', 0)}",
        f"High-risk news: {payload.get('high_risk_news', 0)}",
    ]
    top_news = payload.get("top_news")
    if isinstance(top_news, dict):
        lines.append(f"Top news: {top_news.get('title', '')} ({top_news.get('risk_score', '')})")
    top_coin = payload.get("top_coin")
    if isinstance(top_coin, dict):
        lines.append(f"Top coin: {top_coin.get('symbol', '')} ({top_coin.get('final_score', '')})")
    return "\n".join(lines)


def format_job(payload: dict[str, Any]) -> str:
    lines = [
        f"Job: {payload.get('job_id')}",
        f"Status: {payload.get('status')} / {payload.get('stage')}",
        f"Message: {payload.get('message')}",
    ]
    for key in ("crawler", "dedupe", "agent", "ranking"):
        stage = payload.get(key)
        if isinstance(stage, dict):
            lines.append(
                f"{key}: {stage.get('status')} {stage.get('percent', 0)}% - {stage.get('message', '')}"
            )
    if payload.get("error"):
        lines.append(f"Error: {payload.get('error')}")
    return "\n".join(lines)


def cmd_analyze_news(args: argparse.Namespace) -> Any:
    return request_json("POST", "/api/chat", {"message": args.text})


def cmd_health(_: argparse.Namespace) -> Any:
    return request_json("GET", "/api/health")


def cmd_assistant(args: argparse.Namespace) -> Any:
    context = json.loads(args.context) if args.context else {}
    return request_json("POST", "/api/risk-assistant", {"question": args.question, "context": context})


def cmd_overview(args: argparse.Namespace) -> Any:
    return request_json("GET", f"/api/rankings/overview?{query({'date': args.date})}")


def cmd_news(args: argparse.Namespace) -> Any:
    return request_json("GET", f"/api/rankings/news?{query({'date': args.date, 'limit': args.limit})}")


def cmd_high_risk_news(args: argparse.Namespace) -> Any:
    payload = request_json("GET", f"/api/rankings/news?{query({'date': args.date, 'limit': 0})}")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    filtered = [
        item for item in items
        if isinstance(item, dict) and number(item.get("risk_score")) >= args.min_score
    ][: args.limit]
    if isinstance(payload, dict):
        payload = {**payload, "items": filtered}
    return payload


def cmd_news_detail(args: argparse.Namespace) -> Any:
    path = f"/api/rankings/news/{urllib.parse.quote(args.news_id)}?{query({'date': args.date})}"
    return request_json("GET", path)


def cmd_coins(args: argparse.Namespace) -> Any:
    return request_json("GET", f"/api/rankings/coins?{query({'date': args.date, 'limit': args.limit})}")


def cmd_coin_detail(args: argparse.Namespace) -> Any:
    path = f"/api/rankings/coins/{urllib.parse.quote(args.symbol)}?{query({'date': args.date})}"
    return request_json("GET", path)


def cmd_start_update(_: argparse.Namespace) -> Any:
    return request_json("POST", "/api/rankings/update-news/jobs")


def cmd_update_status(args: argparse.Namespace) -> Any:
    if args.job_id:
        return request_json("GET", f"/api/rankings/update-news/jobs/{urllib.parse.quote(args.job_id)}")
    return request_json("GET", "/api/rankings/update-news/jobs/current")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call the CryptoRisk API")
    parser.add_argument("--base-url", default="", help="override API base URL; defaults to CRYPTO_RISK_API_BASE or public site")
    parser.add_argument("--timeout", type=float, default=0, help="request timeout in seconds; defaults to 90")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="check API health")
    health.set_defaults(func=cmd_health)

    analyze = subparsers.add_parser("analyze-news", help="analyze one crypto news/event text")
    analyze.add_argument("text")
    analyze.set_defaults(func=cmd_analyze_news)

    assistant = subparsers.add_parser("assistant", help="ask the risk assistant")
    assistant.add_argument("question")
    assistant.add_argument("--context", default="")
    assistant.set_defaults(func=cmd_assistant)

    overview = subparsers.add_parser("overview", help="get risk overview")
    overview.add_argument("--date", default="24h")
    overview.set_defaults(func=cmd_overview)

    news = subparsers.add_parser("news", help="get news risk ranking")
    news.add_argument("--date", default="24h")
    news.add_argument("--limit", type=int, default=10)
    news.set_defaults(func=cmd_news)

    high = subparsers.add_parser("high-risk-news", help="get high-risk news filtered by score")
    high.add_argument("--date", default="24h")
    high.add_argument("--limit", type=int, default=10)
    high.add_argument("--min-score", type=int, default=70)
    high.set_defaults(func=cmd_high_risk_news)

    detail = subparsers.add_parser("news-detail", help="get one news item by id")
    detail.add_argument("news_id")
    detail.add_argument("--date", default="24h")
    detail.set_defaults(func=cmd_news_detail)

    coins = subparsers.add_parser("coins", help="get coin risk ranking")
    coins.add_argument("--date", default="24h")
    coins.add_argument("--limit", type=int, default=10)
    coins.set_defaults(func=cmd_coins)

    coin = subparsers.add_parser("coin-detail", help="get one coin risk detail")
    coin.add_argument("symbol")
    coin.add_argument("--date", default="24h")
    coin.set_defaults(func=cmd_coin_detail)

    start = subparsers.add_parser("start-update", help="start async news update job")
    start.set_defaults(func=cmd_start_update)

    status = subparsers.add_parser("update-status", help="check async news update job")
    status.add_argument("--job-id", default="")
    status.set_defaults(func=cmd_update_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.base_url:
        os.environ["CRYPTO_RISK_API_BASE"] = args.base_url
    if args.timeout:
        os.environ["CRYPTO_RISK_TIMEOUT"] = str(args.timeout)
    payload = args.func(args)
    emit(payload, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
