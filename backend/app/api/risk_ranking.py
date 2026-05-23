from fastapi import APIRouter, Query

from app.agents.ranking_agent.graph import run_ranking_agent


router = APIRouter(prefix="/api/rankings", tags=["ranking-agent"])


def _overview(date: str | None):
    return run_ranking_agent("overview", date_filter=date, limit=10)


def _news(date: str | None, limit: int):
    return run_ranking_agent("news", date_filter=date, limit=limit)


def _coins(date: str | None, limit: int):
    return run_ranking_agent("coins", date_filter=date, limit=limit)


@router.get("/overview")
def ranking_overview(date: str | None = Query(default=None)):
    return _overview(date)


@router.get("/news")
def news_ranking(
    date: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
):
    return _news(date, limit)


@router.get("/coins")
def coin_ranking(
    date: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
):
    return _coins(date, limit)
