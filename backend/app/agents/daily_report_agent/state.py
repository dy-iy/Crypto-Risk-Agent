from typing import Literal, TypedDict


DailyReportRange = Literal["24h", "7d"]


class DailyReportState(TypedDict, total=False):
    date_filter: str
    range: DailyReportRange
    user_id: str
    user_display_name: str
    user_profile: dict[str, object]
    news_items: list[dict[str, object]]
    coin_items: list[dict[str, object]]
    signals: dict[str, object]
    llm_draft: dict[str, object]
    report: dict[str, object]
    errors: list[str]
