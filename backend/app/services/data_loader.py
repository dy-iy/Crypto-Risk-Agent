from __future__ import annotations

import json
import math
import re
import uuid
from functools import lru_cache
from pathlib import Path

import pandas as pd


MASTERED_NEWS_PATH = Path(__file__).resolve().parents[1] / "data" / "mastered_news.csv"
DATA_PATH = MASTERED_NEWS_PATH
RAW_NEWS_QUEUE_PATH = Path(__file__).resolve().parents[1] / "data" / "raw_news.csv"
LEGACY_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "raw_300_news.csv"
SCORED_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "scored_news.json"

TITLE_FIELDS = ["title", "headline", "标题", "新闻标题"]
CONTENT_FIELDS = ["content", "text", "body", "summary", "内容", "正文", "摘要"]
DATE_FIELDS = ["published_at", "date", "time", "时间", "发布时间"]
ID_FIELDS = ["news_id", "id", "新闻id", "新闻ID"]
RISK_SCORE_FIELDS = ["risk_score", "score", "风险分数", "风险评分"]
RISK_TYPE_FIELDS = ["risk_type", "category", "risk_category", "风险类型", "风险类别"]
RISK_LEVEL_FIELDS = ["risk_level", "level", "风险等级"]
EVIDENCE_FIELDS = ["evidence", "reason", "explanation", "风险理由", "证据"]


def first_value(row: dict[str, object], fields: list[str], default: object = "") -> object:
    for field in fields:
        value = row.get(field)
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            text = str(value).strip()
            if text:
                return text
    return default


def shorten(text: str, limit: int = 120) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def derive_title(content: str) -> str:
    stripped = str(content or "").strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    first_sentence = re.split(r"[。！？.!?]", first_line)[0]
    return shorten(first_sentence or first_line or "未命名新闻", 56)


def _read_csv(path: Path) -> list[dict[str, object]]:
    last_error: Exception | None = None
    for encoding in ["utf-8-sig", "utf-8", "gbk"]:
        try:
            dataframe = pd.read_csv(path, encoding=encoding)
            dataframe = dataframe.fillna("")
            return dataframe.to_dict(orient="records")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _read_json(path: Path) -> list[dict[str, object]]:
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ["items", "data", "news", "records"]:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


@lru_cache(maxsize=4)
def read_raw_news_records(path_value: str | None = None) -> list[dict[str, object]]:
    path = Path(path_value) if path_value else DATA_PATH
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        return _read_json(path)
    return _read_csv(path)


def normalize_news_record(row: dict[str, object], index: int) -> dict[str, object]:
    content = str(first_value(row, CONTENT_FIELDS, ""))
    title = str(first_value(row, TITLE_FIELDS, "")) or derive_title(content)
    published_at = str(first_value(row, DATE_FIELDS, ""))
    news_id = str(first_value(row, ID_FIELDS, index))

    return {
        "id": news_id,
        "news_id": news_id,
        "csv_order": index,
        "title": title,
        "content": content,
        "date": published_at[:10] if published_at else "",
        "published_at": published_at,
        "risk_score": first_value(row, RISK_SCORE_FIELDS, None),
        "risk_level": str(first_value(row, RISK_LEVEL_FIELDS, "")),
        "risk_type": str(first_value(row, RISK_TYPE_FIELDS, "")),
        "evidence": str(first_value(row, EVIDENCE_FIELDS, "")),
        "raw": row,
    }


def load_normalized_news(path_value: str | None = None) -> list[dict[str, object]]:
    return [
        normalize_news_record(row, index)
        for index, row in enumerate(read_raw_news_records(path_value), start=1)
    ]


def load_scored_news(path_value: str | None = None) -> list[dict[str, object]]:
    path = Path(path_value) if path_value else SCORED_DATA_PATH
    if not path.exists() or path.stat().st_size == 0:
        return []

    with path.open("r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    return []


def _write_text_with_replace_fallback(path: Path, content: str) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        file.write(content)
    try:
        temp_path.replace(path)
    except PermissionError:
        with path.open("w", encoding="utf-8") as file:
            file.write(content)
        try:
            temp_path.unlink()
        except OSError:
            pass


def save_scored_news(items: list[dict[str, object]], path_value: str | None = None) -> None:
    path = Path(path_value) if path_value else SCORED_DATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_with_replace_fallback(
        path,
        json.dumps(items, ensure_ascii=False, indent=2),
    )


def clear_raw_news_queue(path_value: str | None = None) -> None:
    path = Path(path_value) if path_value else RAW_NEWS_QUEUE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "新闻id,时间,内容\n"

    if path.exists():
        for encoding in ["utf-8-sig", "utf-8", "gbk"]:
            try:
                with path.open("r", encoding=encoding) as file:
                    first_line = file.readline()
                if first_line.strip():
                    header = first_line if first_line.endswith("\n") else f"{first_line}\n"
                break
            except UnicodeDecodeError:
                continue

    _write_text_with_replace_fallback(path, header)
    read_raw_news_records.cache_clear()
