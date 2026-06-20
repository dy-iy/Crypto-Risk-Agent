# Experiment: Three Risk Labeling Methods

This directory contains a 100-row crypto market news test set and three independent
labeling methods for comparison experiments.

## Layout

```text
experiment/
  data/
    crypto_market_news_100.csv
    crypto_market_news_100_labeled.csv
    selection_summary.json

  chat_agent/
    run_chat_agent.py
    chat_agent_results.csv

  llm_ranking/
    run_llm_ranking.py
    llm_ranking_results.csv

  risk_scanner/
    run_risk_scanner.py
    risk_scanner_results.csv
```

## Output Fields

Each method writes the same CSV fields:

- `新闻id`
- `原始新闻id`
- `时间`
- `标题`
- `内容`
- `链接`
- `事件`
- `风险分数`
- `风险等级`
- `风险类别`
- `gold_score`
- `gold_level`
- `gold_type`

The method CSV `gold_*` fields are kept for compatibility. Manual gold labels should be
maintained in `experiment/data/crypto_market_news_100_labeled.csv`.

## Run

From the repository root:

```bash
backend/.venv/bin/python experiment/chat_agent/run_chat_agent.py --concurrency 3
backend/.venv/bin/python experiment/llm_ranking/run_llm_ranking.py
backend/.venv/bin/python experiment/risk_scanner/run_risk_scanner.py
backend/.venv/bin/python experiment/evaluate.py
```

Useful options:

```bash
backend/.venv/bin/python experiment/risk_scanner/run_risk_scanner.py --limit 5
backend/.venv/bin/python experiment/chat_agent/run_chat_agent.py --resume --concurrency 3
backend/.venv/bin/python experiment/llm_ranking/run_llm_ranking.py --concurrency 8 --output experiment/llm_ranking/llm_ranking_results.csv
backend/.venv/bin/python experiment/evaluate.py --score-tolerance 10
```

## Notes

- Rows are sorted by `时间` descending before labeling.
- `新闻id` is regenerated as `1..N`; source IDs are preserved in `原始新闻id`.
- `chat_agent` can label multiple news items concurrently with `--concurrency`. Keep this
  lower than `llm_ranking` because chat_agent may run parallel LLM branch checks internally.
- `llm_ranking` uses the ranking LLM node in strict mode with async concurrent calls. If the
  LLM call fails or does not return a pure LLM result, the script stops instead of falling
  back to rules.
- `risk_scanner` uses `backend/app/agents/chat_agent/tools/risk_scanner.py`.
- `evaluate.py` compares each method result with the unified gold CSV and writes
  `evaluation.json` into each method directory.
