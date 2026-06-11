from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


def load_news_risk_agent_with_llm_stub():
    llm_service_stub = types.ModuleType("app.services.llm_news_risk_service")
    llm_service_stub.analyze_news_with_llm = lambda *args, **kwargs: {}
    with patch.dict(sys.modules, {"app.services.llm_news_risk_service": llm_service_stub}):
        sys.modules.pop("app.agents.ranking_agent.news_risk_agent", None)
        return importlib.import_module("app.agents.ranking_agent.news_risk_agent")


class NewsRiskAgentCachedSourceTest(unittest.TestCase):
    def test_cached_llm_source_is_preserved(self) -> None:
        module = load_news_risk_agent_with_llm_stub()
        state = {
            "raw_dataset_empty": False,
            "score_missing": False,
            "filtered_news": [
                {
                    "news_id": "n1",
                    "title": "cached news",
                    "risk_score": 80,
                    "risk_level": "高风险",
                    "risk_type": "异常行情波动风险",
                    "evidence": "evidence",
                    "summary": "summary",
                    "coins": ["BTC"],
                    "llm_source": "llm",
                }
            ],
            "scored_dataset": [
                {
                    "news_id": "n1",
                    "risk_score": 80,
                    "risk_level": "高风险",
                    "risk_type": "异常行情波动风险",
                    "evidence": "evidence",
                    "summary": "summary",
                    "coins": ["BTC"],
                    "llm_source": "llm",
                }
            ],
        }

        result = module.news_risk_agent(state)

        self.assertEqual(result["scored_news"][0]["llm_analysis"]["source"], "llm")


if __name__ == "__main__":
    unittest.main()
