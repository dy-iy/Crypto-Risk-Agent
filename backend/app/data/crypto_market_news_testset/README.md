# Crypto Market News Test Set

This folder contains a 100-row representative test set sampled from
`backend/app/data/mastered_news.csv` for event risk analysis experiments.

Files:

- `crypto_market_news_100.csv`: primary test set, preserving the original source columns.
- `crypto_market_news_100_labeled.csv`: same rows with an additional `测试集类别` sampling bucket.
- `selection_summary.json`: source path, row count, date span, category quotas, and selection notes.

Selection principles:

- Keep only cryptocurrency-market-related news.
- Prefer event-risk scenarios such as regulation, stablecoins, ETF and institutional flows,
  exchange and derivatives changes, security incidents, DeFi protocols, on-chain flows,
  price volatility, macro shocks, and public-chain infrastructure.
- Filter generic finance news and promotional campaign items unless they affect market
  structure, listings, derivatives, settlement, liquidity, or risk exposure.
- Spread rows across the available date range where possible to avoid sampling only one day.
