---
name: crypto-risk-agent
description: "Use this skill when a user asks OpenClaw, ArkClaw, or Codex to use this CryptoRisk project: analyze cryptocurrency news, announcements, exchange/project incidents, on-chain security events, rumors, or alerts for financial risk; query high-risk crypto news; inspect token/coin risk rankings and details; ask follow-up questions about risk evidence, score, impact, or mitigation; or refresh/check the project's news ranking data through the FastAPI multi-agent backend."
---

# Crypto Risk Agent

## Purpose

Use the CryptoRisk FastAPI backend through `scripts/crypto_risk_api.py` instead of reimplementing scoring logic. The backend runs the project's multi-agent risk workflow for crypto news, exchange/project announcements, abnormal exchange behavior, project events, and on-chain security incidents.

Default public API base: `https://kassa-wiki.top`

## Operating Rules

- Prefer the bundled script for API calls; it handles base URL, JSON requests, and readable Markdown output.
- Use `--json` when you need exact fields for further reasoning.
- Use `--base-url` only when the user explicitly asks for another deployment. For this project, frontend code must request relative `/api/xxx` paths only.
- Do not trigger update/crawl jobs unless the user explicitly asks to refresh, crawl, or update news.
- If editing the project, do not run `uvicorn main:app --reload`, `npm run dev`, `npm run build`, or `pm2`.

## Command Map

Run commands from `skills/crypto-risk-agent/` or pass the script's absolute path.

```bash
python3 scripts/crypto_risk_api.py health
python3 scripts/crypto_risk_api.py analyze-news "某 DeFi 项目疑似被攻击，资金池出现异常大额转出，官方尚未发布公告。"
python3 scripts/crypto_risk_api.py high-risk-news --date 24h --limit 10 --min-score 70
python3 scripts/crypto_risk_api.py news --date 7d --limit 10
python3 scripts/crypto_risk_api.py overview --date 24h
python3 scripts/crypto_risk_api.py coins --date 24h --limit 10
python3 scripts/crypto_risk_api.py coin-detail BTC --date 7d
python3 scripts/crypto_risk_api.py assistant "为什么这条新闻评分这么高？" --context '{"symbol":"BTC"}'
```

Useful global options:

```bash
python3 scripts/crypto_risk_api.py --json analyze-news "..."
python3 scripts/crypto_risk_api.py --timeout 120 high-risk-news --date 24h
python3 scripts/crypto_risk_api.py --base-url https://kassa-wiki.top overview --date 24h
```

## Task Routing

### Analyze a Single Item

Use `analyze-news` when the user provides a news article, alert, announcement, incident description, suspicious market event, or rumor.

When answering, include:
- risk level and score
- risk status and confidence
- primary categories or scenarios
- key supporting evidence and counter-evidence
- affected assets/entities
- practical mitigation advice

### Explain an Existing Result

Use `assistant` when the user asks why a score is high/low, what evidence matters, how to interpret a report, or what action to take next. Pass available report, selected text, symbol, news id, or page context through `--context` as compact JSON.

### Query Recent Risk

Use `high-risk-news` for "today's high-risk crypto news", "recent severe events", or "top risky news".

Date guidance:
- `24h`: today / recent 24 hours
- `7d`: recent week
- `all`: all available data, only when requested

### Query Coin or Token Risk

Use `coins` for ranked token risk lists. Use `coin-detail SYMBOL` for a specific asset.

When answering, include symbol, final score, risk level, main risk type, news count, top related news, and a short mitigation note if available.

### Refresh News Data

Use only on explicit refresh/update requests:

```bash
python3 scripts/crypto_risk_api.py start-update
python3 scripts/crypto_risk_api.py update-status
python3 scripts/crypto_risk_api.py update-status --job-id JOB_ID
```

## Response Style

For user-facing answers, avoid dumping raw JSON unless asked. Prefer a concise risk briefing:

```text
结论：高风险，评分 82/100，置信度中高。
主要原因：...
关键证据：...
影响对象：...
建议动作：...
不确定性：...
```

Be explicit about uncertainty. If the backend returns suspected/uncertain status or weak evidence, say the claim needs confirmation instead of presenting it as verified.

## References

Read `references/api-contracts.md` when endpoint paths, parameters, response fields, or exact examples are needed.
