from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from dotenv import load_dotenv


DATA_DIR = Path(__file__).resolve().parent
MASTERED_NEWS_CSV_PATH = DATA_DIR / "mastered_news.csv"
RAW_NEWS_CSV_PATH = MASTERED_NEWS_CSV_PATH
LEGACY_NEWS_CSV_PATH = DATA_DIR / "raw_300_news.csv"

load_dotenv(DATA_DIR.parent.parent / ".env")
load_dotenv(DATA_DIR.parent / ".env")

NEWS_COLUMNS = ["新闻id", "时间", "内容", "链接"]
DEFAULT_BINANCE_NEWS_URL = "https://www.binance.com/bapi/composite/v4/friendly/pgc/feed/news/list"
DEFAULT_BINANCE_NEWS_PAGE_URL = "https://www.binance.com/zh-CN/square/news/all"
BINANCE_NEWS_URL = os.getenv("BINANCE_NEWS_URL", DEFAULT_BINANCE_NEWS_URL)
BINANCE_NEWS_PAGE_URL = os.getenv("BINANCE_NEWS_PAGE_URL", DEFAULT_BINANCE_NEWS_PAGE_URL)


def _configured_proxies() -> dict[str, str] | None:
    proxy_url = os.getenv("BINANCE_PROXY_URL", "").strip()
    http_proxy = os.getenv("BINANCE_HTTP_PROXY", "").strip()
    https_proxy = os.getenv("BINANCE_HTTPS_PROXY", "").strip()

    if proxy_url:
        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies or None


def _proxy_status() -> dict[str, object]:
    proxies = _configured_proxies()
    if proxies:
        return {
            "proxy_enabled": True,
            "proxy_source": "BINANCE_PROXY_URL/BINANCE_HTTP_PROXY/BINANCE_HTTPS_PROXY",
        }

    if os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("https_proxy") or os.getenv("http_proxy"):
        return {
            "proxy_enabled": True,
            "proxy_source": "HTTP_PROXY/HTTPS_PROXY",
        }

    return {
        "proxy_enabled": False,
        "proxy_source": "",
    }


def _endpoint_status() -> dict[str, object]:
    return {
        "news_url_overridden": BINANCE_NEWS_URL != DEFAULT_BINANCE_NEWS_URL,
        "page_url_overridden": BINANCE_NEWS_PAGE_URL != DEFAULT_BINANCE_NEWS_PAGE_URL,
    }


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=NEWS_COLUMNS)

    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gbk"]:
        try:
            return pd.read_csv(path, encoding=encoding).fillna("")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.DataFrame(columns=NEWS_COLUMNS)


def _normalize_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    normalized = dataframe.copy()
    for column in NEWS_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    return normalized[NEWS_COLUMNS]


def _write_news_csv(dataframe: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _normalize_columns(dataframe).to_csv(path, index=False, encoding="utf-8-sig")


def _is_empty_news_csv(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        return _read_csv(path).empty
    except Exception:
        return True


def _seed_master_dataset(master_csv_path: Path, seed_csv_path: Path = LEGACY_NEWS_CSV_PATH) -> int:
    if not _is_empty_news_csv(master_csv_path) or not seed_csv_path.exists():
        return 0

    seed_data = _normalize_columns(_read_csv(seed_csv_path))
    if seed_data.empty:
        return 0

    seed_data["新闻id"] = seed_data.apply(
        lambda row: str(row.get("新闻id") or _build_news_id(row.get("链接"), row.get("时间"), row.get("内容"))),
        axis=1,
    )
    _write_news_csv(seed_data, master_csv_path)
    return len(seed_data)


def _build_news_id(link: object, published_at: object, content: object) -> str:
    fingerprint = "|".join(
        [
            str(link or "").strip(),
            str(published_at or "").strip(),
            str(content or "").strip(),
        ]
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]


def _dedupe_key(row: pd.Series) -> str:
    link = str(row.get("链接") or "").strip()
    if link:
        return f"link:{link}"
    return f"content:{_build_news_id('', row.get('时间'), row.get('内容'))}"


def get_latest_news_time(csv_path: Path) -> dt.datetime:
    if not csv_path.exists():
        return dt.datetime(2020, 1, 1)

    try:
        dataframe = _read_csv(csv_path)
        if "时间" not in dataframe.columns:
            return dt.datetime(2020, 1, 1)

        times = pd.to_datetime(dataframe["时间"], errors="coerce").dropna()
        if times.empty:
            return dt.datetime(2020, 1, 1)
        return times.max().to_pydatetime()
    except Exception:
        return dt.datetime(2020, 1, 1)


def parse_binance_timestamp(timestamp: object) -> dt.datetime:
    value = int(timestamp)
    if value > 10**12:
        return dt.datetime.fromtimestamp(value / 1000)
    return dt.datetime.fromtimestamp(value)


def update_master_dataset(
    new_records: list[dict[str, object]],
    master_csv_path: Path = MASTERED_NEWS_CSV_PATH,
) -> dict[str, int]:
    master = _normalize_columns(_read_csv(master_csv_path))
    new_data = _normalize_columns(pd.DataFrame(new_records, columns=NEWS_COLUMNS))
    existing_count = len(master)
    fetched_count = len(new_data)
    if new_data.empty:
        return {
            "existing_count": existing_count,
            "fetched_count": 0,
            "added_count": 0,
            "total_count": existing_count,
        }

    combined = pd.concat([master, new_data], ignore_index=True)
    combined["新闻id"] = combined.apply(
        lambda row: str(row.get("新闻id") or _build_news_id(row.get("链接"), row.get("时间"), row.get("内容"))),
        axis=1,
    )
    combined["_dedupe_key"] = combined.apply(_dedupe_key, axis=1)
    combined["_parsed_time"] = pd.to_datetime(combined["时间"], errors="coerce")

    combined = combined.drop_duplicates(subset=["_dedupe_key"], keep="first")
    combined = combined.sort_values(by="_parsed_time", ascending=False, na_position="last")
    combined = combined.drop(columns=["_dedupe_key", "_parsed_time"])
    combined = _normalize_columns(combined)

    _write_news_csv(combined, master_csv_path)
    total_count = len(combined)
    return {
        "existing_count": existing_count,
        "fetched_count": fetched_count,
        "added_count": max(0, total_count - existing_count),
        "total_count": total_count,
    }


def _build_session() -> requests.Session:
    session = requests.Session()
    proxies = _configured_proxies()
    if proxies:
        session.proxies.update(proxies)
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": BINANCE_NEWS_PAGE_URL,
            "Origin": "https://www.binance.com",
            "clienttype": "web",
            "lang": "zh-CN",
        }
    )
    return session


def _read_response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        preview = response.text[:120].replace("\n", " ").strip()
        detail = f"non-JSON response from news API: {preview}" if preview else "empty response from news API"
        raise ValueError(detail) from exc

    if not isinstance(payload, dict):
        raise ValueError("unexpected news API response shape")
    return payload


def fetch_binance_news(
    start_time: dt.datetime,
    end_time: dt.datetime,
    max_page: int = 500,
    page_size: int = 20,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> tuple[list[dict[str, object]], int]:
    session = _build_session()
    session.get(BINANCE_NEWS_PAGE_URL, timeout=15)

    params: dict[str, Any] = {
        "pageIndex": 1,
        "pageSize": page_size,
        "strategy": 6,
        "tagId": 0,
        "featured": "false",
    }

    records: list[dict[str, object]] = []
    fetched_count = 0
    stop = False

    for page in range(1, max_page + 1):
        if progress_callback:
            progress_callback(
                {
                    "stage": "crawler",
                    "current": page,
                    "total": max_page,
                    "fetched_count": fetched_count,
                    "message": f"正在请求第 {page} 页",
                }
            )
        params["pageIndex"] = page
        response = session.get(BINANCE_NEWS_URL, params=params, timeout=20)
        response.raise_for_status()
        payload = _read_response_json(response)

        payload_data = payload.get("data")
        data = payload_data.get("vos", []) if isinstance(payload_data, dict) else []
        if not data:
            break

        for item in data:
            if not isinstance(item, dict):
                continue
            raw_date = item.get("date")
            if not raw_date:
                continue

            try:
                news_date = parse_binance_timestamp(raw_date)
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            if news_date > end_time:
                continue
            if news_date < start_time:
                stop = True
                break

            title = str(item.get("title") or "").strip()
            subtitle = str(item.get("subTitle") or "").strip()
            content = f"{title} {subtitle}".strip()
            link = str(item.get("webLink") or "").strip()
            published_at = news_date.strftime("%Y-%m-%d %H:%M:%S")

            records.append(
                {
                    "新闻id": _build_news_id(link, published_at, content),
                    "时间": published_at,
                    "内容": content,
                    "链接": link,
                }
            )
            fetched_count += 1

        if stop:
            break

    if progress_callback:
        progress_callback(
            {
                "stage": "crawler",
                "current": max(1, page if "page" in locals() else 1),
                "total": max(1, page if "page" in locals() else 1),
                "fetched_count": fetched_count,
                "message": f"爬虫完成，抓取 {fetched_count} 条",
            }
        )

    return records, fetched_count


def update_news_dataset(
    master_csv_path: Path = MASTERED_NEWS_CSV_PATH,
    lookback_hours: int = 24 * 7,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    seeded_count = _seed_master_dataset(master_csv_path)
    end_time = dt.datetime.now()
    incremental_start = get_latest_news_time(master_csv_path) - dt.timedelta(hours=1)
    lookback_start = end_time - dt.timedelta(hours=lookback_hours)
    start_time = max(incremental_start, lookback_start)
    crawler_error = ""
    try:
        new_records, fetched_count = fetch_binance_news(
            start_time,
            end_time,
            progress_callback=progress_callback,
        )
    except (requests.RequestException, ValueError) as exc:
        new_records = []
        fetched_count = 0
        crawler_error = str(exc)
        if progress_callback:
            progress_callback(
                {
                    "stage": "crawler",
                    "current": 0,
                    "total": 0,
                    "fetched_count": 0,
                    "message": "新闻源连接失败，使用本地新闻集继续",
                    "error": crawler_error,
                }
            )

    merge_result = (
        update_master_dataset(new_records, master_csv_path)
        if new_records
        else {
            "existing_count": len(_read_csv(master_csv_path)),
            "fetched_count": fetched_count,
            "added_count": 0,
            "total_count": len(_read_csv(master_csv_path)),
        }
    )

    return {
        **merge_result,
        "seeded_count": seeded_count,
        "lookback_hours": lookback_hours,
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "raw_news_path": str(master_csv_path),
        "mastered_news_path": str(master_csv_path),
        "crawler_error": crawler_error,
        **_proxy_status(),
        **_endpoint_status(),
    }


if __name__ == "__main__":
    result = update_news_dataset()
    print(result)
