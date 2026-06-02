# CryptoRisk API Contracts

Base URL defaults to `https://kassa-wiki.top`.

All public app endpoints are under `/api/...`. Nginx maps `/api/` to the FastAPI backend.

## Health

`GET /api/health`

Response:

```json
{"status":"ok"}
```

## Analyze News

`POST /api/chat`

Request:

```json
{"message":"crypto news, announcement, incident, or risk text"}
```

Response:

```json
{
  "status": "success",
  "message": "分析完成",
  "data": {
    "summary": "...",
    "input_type": "news|announcement|incident|unknown",
    "has_risk": true,
    "risk_status": "confirmed|suspected|uncertain",
    "risk_score": 0,
    "final_risk_score": 0,
    "risk_level": "低风险|中风险|高风险",
    "confidence_level": "低|中|高",
    "risk_categories": [],
    "risk_signals": [],
    "evidence": [
      {
        "risk_category": "...",
        "evidence_text": "...",
        "explanation": "..."
      }
    ],
    "impact": [],
    "advice": []
  }
}
```

Important `data` fields:
- `summary`: short event summary.
- `has_risk`: whether risk was detected.
- `risk_status`: `confirmed`, `suspected`, or `uncertain`.
- `risk_score` / `final_risk_score`: 0-100 risk score. Prefer `final_risk_score` when non-zero.
- `risk_level`: Chinese risk level, usually `低风险`, `中风险`, or `高风险`.
- `confidence_level`: model/report confidence.
- `risk_categories`, `primary_category`, `secondary_categories`: risk classification.
- `supporting_evidence`, `counter_evidence`, `evidence`, `evidence_items`: evidence views. Use concise evidence in user-facing summaries.
- `missing_info`, `missing_information`, `unverified_claims`, `overclaiming_risks`: uncertainty and missing facts.
- `affected_entities`, `affected_assets`, `impact`, `structured_impact`: impact scope.
- `advice`, `priority`, `action_type`: recommended handling.
- `chat_agent_result`: detailed chat-agent internals for debugging and advanced explanations.

## Analyze News Stream

`POST /api/chat/stream`

Request is the same as `/api/chat`. Response is Server-Sent Events:
- `progress`: workflow progress event
- `result`: final `ChatResponse`
- `error`: failure detail

Use the normal `/api/chat` endpoint for scripted skill calls unless the user specifically needs progress streaming.

## Risk Assistant

`POST /api/risk-assistant`

Request:

```json
{"question":"question text","context":{}}
```

Use this for follow-up explanation when the user asks why a score is high, how to respond, or how to interpret an existing report.

Additional request fields accepted by the backend:
- `selected_text`: quoted text from a page selection.
- `user_question`: question typed after selecting text.
- `context_type`: typed source such as news, coin, report, or portfolio page.
- `page_context`: page metadata including `path`, `page_type`, `news_id`, `symbol`, and `title`.
- `use_portfolio_context`: whether portfolio context should be considered.

## Risk Assistant Stream

`POST /api/risk-assistant/stream`

Server-Sent Events stream of answer chunks. Prefer `/api/risk-assistant` for the bundled script.

## Ranking Overview

`GET /api/rankings/overview?date=24h`

`date` examples:
- `24h`: today/recent 24 hours
- `7d`: recent 7 days
- `all`: all available data
- date string if supported by backend data

Response includes:
- `total_news`
- `high_risk_news`
- `top_news`
- `top_coin`
- `top_news_preview`
- `top_coin_preview`

## News Rankings

`GET /api/rankings/news?date=24h&limit=10`

Each item usually includes:
- `rank`
- `news_id`
- `title`
- `content`
- `published_at`
- `risk_score`
- `risk_level`
- `risk_type`
- `coins`
- `summary`
- `evidence`
- `source_url`

Use `limit=0` to fetch all ranked news when filtering locally.

For "high-risk news", fetch with `limit=0` and filter by `risk_score` locally. The bundled script's `high-risk-news` command does this.

## News Detail

`GET /api/rankings/news/{news_id}?date=24h`

Falls back to `all` internally when a date-filtered lookup misses.

## Coin Rankings

`GET /api/rankings/coins?date=24h&limit=10`

Each item usually includes:
- `rank`
- `symbol`
- `name`
- `final_score`
- `risk_level`
- `news_count`
- `main_risk_type`
- `top_news_title`
- `summary`
- `related_news`

## Coin Detail

`GET /api/rankings/coins/{symbol}?date=24h`

Symbol matching is case-insensitive.

## News Update Job

Start async update:

`POST /api/rankings/update-news/jobs`

Legacy synchronous-style update endpoint:

`POST /api/rankings/update-news`

Get current update job:

`GET /api/rankings/update-news/jobs/current`

Get specific job:

`GET /api/rankings/update-news/jobs/{job_id}`

Use only when the user asks to refresh or crawl news.
