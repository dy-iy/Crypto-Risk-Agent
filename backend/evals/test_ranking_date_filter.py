import unittest
from datetime import datetime, timedelta

from app.services.ranking_aggregation_service import filter_news_by_date


class RankingDateFilterTest(unittest.TestCase):
    def test_recent_windows_do_not_fallback_to_old_news(self) -> None:
        items = [
            {
                "news_id": "old",
                "date": "2024-01-01",
                "published_at": "2024-01-01 08:00:00",
            }
        ]

        self.assertEqual(filter_news_by_date(items, "24h"), [])
        self.assertEqual(filter_news_by_date(items, "7d"), [])
        self.assertEqual(filter_news_by_date(items, datetime.now().date().isoformat()), [])

    def test_recent_windows_keep_matching_news(self) -> None:
        now = datetime.now()
        items = [
            {
                "news_id": "today",
                "date": now.date().isoformat(),
                "published_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "news_id": "week",
                "date": (now - timedelta(days=2)).date().isoformat(),
                "published_at": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
            },
            {
                "news_id": "old",
                "date": "2024-01-01",
                "published_at": "2024-01-01 08:00:00",
            },
        ]

        self.assertEqual([item["news_id"] for item in filter_news_by_date(items, "24h")], ["today"])
        self.assertEqual([item["news_id"] for item in filter_news_by_date(items, "7d")], ["today", "week"])
        self.assertEqual(
            [item["news_id"] for item in filter_news_by_date(items, now.date().isoformat())],
            ["today"],
        )


if __name__ == "__main__":
    unittest.main()
