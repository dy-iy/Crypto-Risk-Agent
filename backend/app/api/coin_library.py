from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.coin_library_service import list_coin_library


router = APIRouter(prefix="/api/coin-library", tags=["coin-library"])


@router.get("")
def coin_library(
    q: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    return list_coin_library(q, limit)
