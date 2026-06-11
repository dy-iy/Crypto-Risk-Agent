import unittest
import importlib
import sys
import types
from unittest.mock import patch


def load_risk_ranking_with_fastapi_stub():
    if "app.api.risk_ranking" in sys.modules:
        return sys.modules["app.api.risk_ranking"]

    fastapi_stub = types.ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.HTTPException = Exception
    fastapi_stub.Query = lambda default=None, *args, **kwargs: default
    ranking_graph_stub = types.ModuleType("app.agents.ranking_agent.graph")
    ranking_graph_stub.run_ranking_agent = lambda *args, **kwargs: {}
    update_news_stub = types.ModuleType("app.data.update_news")
    update_news_stub.update_news_dataset = lambda *args, **kwargs: {"crawler_error": "stubbed"}
    sys.modules.setdefault("fastapi", fastapi_stub)
    sys.modules.setdefault("app.agents.ranking_agent.graph", ranking_graph_stub)
    sys.modules.setdefault("app.data.update_news", update_news_stub)
    return importlib.import_module("app.api.risk_ranking")


class RankingApiCompactionTest(unittest.TestCase):
    def test_public_news_limit_zero_returns_full_list(self) -> None:
        risk_ranking = load_risk_ranking_with_fastapi_stub()
        items = [
            {
                "news_id": str(index),
                "content": "正文" * 500,
                "evidence": "证据" * 150,
                "summary": "摘要" * 150,
            }
            for index in range(120)
        ]

        with patch.object(risk_ranking, "_news", return_value={"items": items, "date": "24h"}) as news:
            response = risk_ranking.news_ranking(date="24h", limit=0)

        news.assert_called_once_with("24h", 0)
        self.assertEqual(len(response["items"]), len(items))
        self.assertEqual(response["items"][0]["content"], items[0]["content"])

    def test_public_coin_limit_zero_returns_compact_bounded_list(self) -> None:
        risk_ranking = load_risk_ranking_with_fastapi_stub()
        related_news = [
            {
                "news_id": str(index),
                "content": "正文" * 500,
                "evidence": "证据" * 150,
                "summary": "摘要" * 150,
            }
            for index in range(10)
        ]
        items = [
            {
                "symbol": f"T{index}",
                "related_news": related_news,
            }
            for index in range(600)
        ]

        with patch.object(risk_ranking, "_coins", return_value={"items": items, "date": "24h"}) as coins:
            response = risk_ranking.coin_ranking(date="24h", limit=0)

        coins.assert_called_once_with("24h", risk_ranking.PUBLIC_COIN_RANKING_FALLBACK_LIMIT)
        self.assertEqual(len(response["items"]), risk_ranking.PUBLIC_COIN_RANKING_FALLBACK_LIMIT)
        for item in response["items"]:
            self.assertEqual(len(item["related_news"]), risk_ranking.MAX_COMPACT_COIN_RELATED_NEWS)
            self.assertTrue(all(news_item["content"] == "" for news_item in item["related_news"]))

    def test_news_detail_keeps_full_content(self) -> None:
        risk_ranking = load_risk_ranking_with_fastapi_stub()
        full_item = {
            "news_id": "n1",
            "content": "完整正文" * 500,
            "evidence": "完整证据" * 100,
        }

        with patch.object(risk_ranking, "_news", return_value={"items": [full_item], "date": "24h"}):
            response = risk_ranking.news_detail("n1", date="24h")

        self.assertEqual(response["content"], full_item["content"])
        self.assertEqual(response["evidence"], full_item["evidence"])


if __name__ == "__main__":
    unittest.main()
