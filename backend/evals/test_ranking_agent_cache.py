import unittest
from unittest.mock import patch

from app.agents.ranking_agent import graph


class RankingAgentCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        graph._run_cached_ranking_agent.cache_clear()

    def test_readonly_ranking_reuses_cached_response_copy(self) -> None:
        with patch.object(graph.ranking_workflow, "invoke", wraps=graph.ranking_workflow.invoke) as invoke:
            first = graph.run_ranking_agent("news", date_filter="24h", limit=5, score_missing=False)
            second = graph.run_ranking_agent("news", date_filter="24h", limit=5, score_missing=False)

        self.assertEqual(invoke.call_count, 1)
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

        first["items"].append({"news_id": "mutated"})
        third = graph.run_ranking_agent("news", date_filter="24h", limit=5, score_missing=False)
        self.assertNotEqual(len(first["items"]), len(third["items"]))

    def test_scoring_requests_bypass_readonly_cache(self) -> None:
        with patch.object(graph.ranking_workflow, "invoke", wraps=graph.ranking_workflow.invoke) as invoke:
            graph.run_ranking_agent("news", date_filter="24h", limit=5, score_missing=True)
            graph.run_ranking_agent("news", date_filter="24h", limit=5, score_missing=True)

        self.assertEqual(invoke.call_count, 2)


if __name__ == "__main__":
    unittest.main()
