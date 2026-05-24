from copy import deepcopy
from datetime import datetime
from threading import Lock, Thread
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from app.agents.ranking_agent.graph import run_ranking_agent
from app.data.update_news import update_news_dataset
from app.services.data_loader import load_normalized_news, load_scored_news, read_raw_news_records, save_scored_news
from app.services.ranking_aggregation_service import filter_news_by_date
from app.tools.ranking_tools import attach_coin_entities


router = APIRouter(prefix="/api/rankings", tags=["ranking-agent"])
_update_lock = Lock()
_jobs_lock = Lock()
_scored_write_lock = Lock()
_update_jobs: dict[str, dict[str, object]] = {}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_progress(label: str) -> dict[str, object]:
    return {
        "label": label,
        "status": "pending",
        "current": 0,
        "total": 0,
        "percent": 0,
        "message": "等待中",
    }


def _new_update_job() -> dict[str, object]:
    job_id = uuid4().hex
    return {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": "等待启动新闻更新任务",
        "crawler": _new_progress("爬虫"),
        "dedupe": _new_progress("去重入库"),
        "agent": _new_progress("Agent 标注"),
        "ranking": _new_progress("排行榜"),
        "result": None,
        "error": "",
        "started_at": "",
        "updated_at": _now_text(),
        "finished_at": "",
    }


def _progress_percent(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(current / total * 100)))


def _update_job(job_id: str, **updates: object) -> None:
    with _jobs_lock:
        job = _update_jobs.get(job_id)
        if not job:
            return
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(job.get(key), dict):
                merged = {**job[key], **value}  # type: ignore[index]
                if "current" in merged or "total" in merged:
                    merged["percent"] = _progress_percent(
                        int(merged.get("current") or 0),
                        int(merged.get("total") or 0),
                    )
                job[key] = merged
            else:
                job[key] = value
        job["updated_at"] = _now_text()


def _get_job(job_id: str) -> dict[str, object] | None:
    with _jobs_lock:
        job = _update_jobs.get(job_id)
        return deepcopy(job) if job else None


def _csv_order(item: dict[str, object]) -> int:
    try:
        return int(str(item.get("csv_order") or item.get("news_id") or item.get("id") or "0"))
    except ValueError:
        return 0


def _build_scored_item(item: dict[str, object], analysis: dict[str, object]) -> dict[str, object]:
    return {
        **item,
        "risk_score": analysis.get("risk_score", 0),
        "risk_level": analysis.get("risk_level", "低风险"),
        "risk_type": analysis.get("risk_type", "异常行情波动风险"),
        "evidence": analysis.get("evidence", ""),
        "summary": analysis.get("summary", ""),
        "coins": analysis.get("coins", []),
        "coin_details": [],
        "llm_analysis": analysis,
    }


def _persist_incremental_scored_item(item: dict[str, object], analysis: dict[str, object]) -> None:
    if not analysis:
        return

    scored_item = _build_scored_item(item, analysis)
    state = attach_coin_entities({"scored_news": [scored_item]})
    enriched_items = state.get("coin_enriched_news", [])
    enriched_item = enriched_items[0] if enriched_items else scored_item
    news_id = str(enriched_item.get("news_id") or enriched_item.get("id"))

    with _scored_write_lock:
        existing_items = load_scored_news()
        merged_by_id = {
            str(existing.get("news_id") or existing.get("id")): existing
            for existing in existing_items
        }
        merged_by_id[news_id] = {
            "news_id": enriched_item.get("news_id"),
            "csv_order": enriched_item.get("csv_order"),
            "title": enriched_item.get("title"),
            "content": enriched_item.get("content"),
            "date": enriched_item.get("date"),
            "published_at": enriched_item.get("published_at"),
            "risk_score": enriched_item.get("risk_score"),
            "risk_level": enriched_item.get("risk_level"),
            "risk_type": enriched_item.get("risk_type"),
            "evidence": enriched_item.get("evidence"),
            "summary": enriched_item.get("summary"),
            "coins": enriched_item.get("coins", []),
            "coin_details": enriched_item.get("coin_details", []),
            "llm_source": analysis.get("source", ""),
        }
        save_scored_news(sorted(merged_by_id.values(), key=_csv_order))


def _run_update_job(job_id: str) -> None:
    if not _update_lock.acquire(blocking=False):
        _update_job(
            job_id,
            status="error",
            stage="blocked",
            message="已有新闻更新任务正在运行",
            error="News update is already running",
            finished_at=_now_text(),
        )
        return

    try:
        _update_job(
            job_id,
            status="running",
            stage="crawler",
            message="爬虫正在抓取近 7 天 Binance Square 新闻",
            started_at=_now_text(),
            crawler={"status": "running", "message": "连接新闻源"},
        )

        def crawler_progress(event: dict[str, object]) -> None:
            total = int(event.get("total") or 0)
            current = int(event.get("current") or 0)
            fetched_count = int(event.get("fetched_count") or 0)
            message = str(event.get("message") or "爬虫运行中")
            status = "error" if event.get("error") else "running"
            _update_job(
                job_id,
                stage="crawler",
                message=message,
                crawler={
                    "status": status,
                    "current": current,
                    "total": total,
                    "fetched_count": fetched_count,
                    "message": message,
                },
            )

        update_result = update_news_dataset(progress_callback=crawler_progress)
        crawler_status = "warning" if update_result.get("crawler_error") else "success"
        _update_job(
            job_id,
            stage="dedupe",
            message="新闻集已合并，正在统计待标注新闻",
            crawler={
                "status": crawler_status,
                "current": 1,
                "total": 1,
                "fetched_count": update_result.get("fetched_count", 0),
                "message": "新闻源不可达，已使用本地新闻集" if update_result.get("crawler_error") else "爬虫完成",
            },
            dedupe={
                "status": "success",
                "current": int(update_result.get("total_count") or 0),
                "total": int(update_result.get("total_count") or 0),
                "message": f"净新增 {update_result.get('added_count', 0)} 条，新闻集共 {update_result.get('total_count', 0)} 条",
            },
        )

        read_raw_news_records.cache_clear()
        unprocessed_before = _count_unprocessed_news("7d")
        _update_job(
            job_id,
            stage="agent",
            message="Agent 正在增量标注未处理新闻",
            agent={
                "status": "running" if unprocessed_before else "success",
                "current": 0,
                "total": unprocessed_before,
                "message": "开始标注" if unprocessed_before else "没有待标注新闻",
            },
        )

        def agent_progress(current: int, total: int, item: dict[str, object]) -> None:
            title = str(item.get("title") or item.get("content") or "")[:42]
            analysis = item.get("_analysis")
            analysis_source = ""
            if isinstance(analysis, dict):
                analysis_source = str(analysis.get("source") or "")
                _persist_incremental_scored_item(item, analysis)
            progress_message = title or "正在标注新闻"
            if analysis_source == "rule_fallback":
                progress_message = f"{progress_message}（DeepSeek 不可用，规则兜底）"
            _update_job(
                job_id,
                stage="agent",
                message=f"Agent 标注 {current}/{total}",
                agent={
                    "status": "running",
                    "current": current,
                    "total": total,
                    "message": progress_message,
                },
                ranking={
                    "status": "running",
                    "current": current,
                    "total": total,
                    "message": "已写入部分结果，排行榜实时可读",
                },
            )

        ranking = run_ranking_agent("all", date_filter="7d", limit=10, progress_callback=agent_progress)
        read_raw_news_records.cache_clear()
        unprocessed_after = _count_unprocessed_news("7d")
        processed_count = max(0, unprocessed_before - unprocessed_after)
        _update_job(
            job_id,
            stage="ranking",
            message="正在刷新近 7 天排行榜",
            agent={
                "status": "success",
                "current": processed_count or unprocessed_before,
                "total": unprocessed_before,
                "message": f"已处理 {processed_count} 条",
            },
            ranking={
                "status": "success",
                "current": 1,
                "total": 1,
                "message": "近 1 天 / 近 7 天排行榜已刷新",
            },
        )

        message = "今日新闻已更新，近 7 天未处理新闻已完成增量评分，排行榜已刷新。"
        if update_result.get("crawler_error"):
            message = "Binance 新闻源暂时不可达，已使用本地新闻集完成近 7 天增量评分和排行榜刷新。"

        result = {
            "status": "success",
            "message": message,
            "crawler": update_result,
            "agent": {
                "unprocessed_before": unprocessed_before,
                "processed_count": processed_count,
                "unprocessed_after": unprocessed_after,
            },
            "ranking": ranking,
        }
        _update_job(
            job_id,
            status="success",
            stage="done",
            message=message,
            result=result,
            finished_at=_now_text(),
        )
    except Exception as exc:
        _update_job(
            job_id,
            status="error",
            stage="error",
            message=f"新闻更新失败：{exc}",
            error=str(exc),
            finished_at=_now_text(),
        )
    finally:
        _update_lock.release()


def _overview(date: str | None):
    return run_ranking_agent("overview", date_filter=date, limit=10, score_missing=False)


def _news(date: str | None, limit: int):
    return run_ranking_agent("news", date_filter=date, limit=limit, score_missing=False)


def _coins(date: str | None, limit: int):
    return run_ranking_agent("coins", date_filter=date, limit=limit, score_missing=False)


def _is_complete_scored_item(item: dict[str, object]) -> bool:
    if item.get("llm_source") == "rule_fallback":
        return False
    return bool(
        item.get("risk_score") is not None
        and item.get("risk_level")
        and item.get("risk_type")
        and item.get("evidence")
    )


def _count_unprocessed_news(date_filter: str | None = None) -> int:
    raw_items = filter_news_by_date(load_normalized_news(), date_filter)
    scored_ids = {
        str(item.get("news_id") or item.get("id"))
        for item in load_scored_news()
        if _is_complete_scored_item(item)
    }
    return sum(
        1
        for item in raw_items
        if str(item.get("news_id") or item.get("id")) not in scored_ids
    )


@router.get("/overview")
def ranking_overview(date: str | None = Query(default=None)):
    return _overview(date)


@router.post("/update-news")
def update_today_news():
    if not _update_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="News update is already running")

    try:
        update_result = update_news_dataset()
        read_raw_news_records.cache_clear()
        unprocessed_before = _count_unprocessed_news()
        ranking = run_ranking_agent("all", date_filter="24h", limit=10)
        read_raw_news_records.cache_clear()
        unprocessed_after = _count_unprocessed_news()
        message = "今日新闻已更新，未处理新闻已完成增量评分，24h 排行榜已刷新。"
        if update_result.get("crawler_error"):
            message = "Binance 新闻源暂时不可达，已使用本地新闻集完成增量评分和排行榜刷新。"
        return {
            "status": "success",
            "message": message,
            "crawler": update_result,
            "agent": {
                "unprocessed_before": unprocessed_before,
                "processed_count": max(0, unprocessed_before - unprocessed_after),
                "unprocessed_after": unprocessed_after,
            },
            "ranking": ranking,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"News update failed: {exc}") from exc
    finally:
        _update_lock.release()


@router.post("/update-news/jobs")
def start_update_today_news_job():
    job = _new_update_job()
    job_id = str(job["job_id"])
    with _jobs_lock:
        _update_jobs[job_id] = job

    thread = Thread(target=_run_update_job, args=(job_id,), daemon=True)
    thread.start()
    return _get_job(job_id)


@router.get("/update-news/jobs/{job_id}")
def get_update_today_news_job(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="News update job not found")
    return job


@router.get("/news")
def news_ranking(
    date: str | None = Query(default=None),
    limit: int = Query(default=10, ge=0, le=5000),
):
    return _news(date, limit)


@router.get("/news/{news_id}")
def news_detail(
    news_id: str,
    date: str | None = Query(default=None),
):
    response = _news(date, 0)
    for item in response.get("items", []):
        if str(item.get("news_id")) == news_id:
            return item
    raise HTTPException(status_code=404, detail="News item not found")


@router.get("/coins")
def coin_ranking(
    date: str | None = Query(default=None),
    limit: int = Query(default=10, ge=0, le=5000),
):
    return _coins(date, limit)


@router.get("/coins/{symbol}")
def coin_detail(
    symbol: str,
    date: str | None = Query(default=None),
):
    response = _coins(date, 0)
    normalized_symbol = symbol.upper()
    for item in response.get("items", []):
        if str(item.get("symbol", "")).upper() == normalized_symbol:
            return item
    raise HTTPException(status_code=404, detail="Coin item not found")
