from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from settings import PROJECT_PATH


VECTOR_DIM = 512
INDEX_VERSION = 1
KNOWLEDGE_ROOT = Path(PROJECT_PATH) / "data" / "knowledge"
RAG_ROOT = Path(PROJECT_PATH) / "data" / "rag"
INDEX_PATH = RAG_ROOT / "knowledge_index.json"


@dataclass
class KnowledgeChunk:
    id: str
    source: str
    title: str
    content: str
    tags: List[str]
    metadata: Dict[str, Any]
    vector: List[float]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_stringify(item) for item in value.values())
    return str(value)


def _tokens(text: str) -> List[str]:
    text = text.lower()
    base_tokens = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]", text)
    # Character bigrams improve Chinese matching without adding external deps.
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chinese_chars[i : i + 2]) for i in range(max(0, len(chinese_chars) - 1))]
    return [*base_tokens, *bigrams]


def _hash_token(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % VECTOR_DIM


def _vectorize(text: str) -> List[float]:
    vector = [0.0] * VECTOR_DIM
    for token in _tokens(text):
        vector[_hash_token(token)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: List[float], right: List[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _keyword_score(query_tokens: List[str], content_tokens: List[str]) -> float:
    if not query_tokens or not content_tokens:
        return 0.0
    content_set = set(content_tokens)
    matched = sum(1 for token in set(query_tokens) if token in content_set)
    return matched / max(1, len(set(query_tokens)))


def _compact_content(parts: List[Any], limit: int = 1800) -> str:
    text = "\n".join(part for part in (_stringify(item).strip() for item in parts) if part)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _make_chunk(
    *,
    chunk_id: str,
    source: str,
    title: str,
    content: str,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> KnowledgeChunk:
    searchable = "\n".join([title, content, " ".join(tags or [])])
    return KnowledgeChunk(
        id=chunk_id,
        source=source,
        title=title,
        content=content,
        tags=tags or [],
        metadata=metadata or {},
        vector=_vectorize(searchable),
    )


class RagService:
    def __init__(self, index_path: Path = INDEX_PATH):
        self.index_path = index_path
        self._chunks: Optional[List[KnowledgeChunk]] = None
        self._loaded_mtime: Optional[float] = None

    def status(self) -> Dict[str, Any]:
        exists = self.index_path.exists()
        payload: Dict[str, Any] = {
            "available": exists,
            "index_path": str(self.index_path),
            "mode": "local_hash_vector+keyword",
            "vector_dim": VECTOR_DIM,
            "chunk_count": 0,
            "updated_at": None,
        }
        if exists:
            try:
                data = _read_json(self.index_path)
                payload["chunk_count"] = len(data.get("chunks", []))
                payload["updated_at"] = data.get("updated_at")
                payload["version"] = data.get("version")
            except Exception as exc:
                payload["available"] = False
                payload["error"] = str(exc)
        return payload

    def rebuild(self) -> Dict[str, Any]:
        chunks = self._collect_chunks()
        RAG_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "local_hash_vector+keyword",
            "vector_dim": VECTOR_DIM,
            "chunks": [asdict(chunk) for chunk in chunks],
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._chunks = chunks
        self._loaded_mtime = self.index_path.stat().st_mtime
        return self.status()

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"query": query, "total": 0, "items": [], "index": self.status()}
        chunks = self._load_or_build()
        filters = filters if isinstance(filters, dict) else {}
        q_vector = _vectorize(query)
        q_tokens = _tokens(query)
        scored = []
        for chunk in chunks:
            if filters.get("source") and chunk.source != filters["source"]:
                continue
            if filters.get("tag") and filters["tag"] not in chunk.tags:
                continue
            haystack = "\n".join([chunk.title, chunk.content, " ".join(chunk.tags)])
            vector_score = _cosine(q_vector, chunk.vector)
            keyword = _keyword_score(q_tokens, _tokens(haystack))
            score = 0.72 * vector_score + 0.28 * keyword
            if score <= 0:
                continue
            scored.append((score, vector_score, keyword, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        limit = max(1, min(int(top_k or 5), 20))
        items = []
        for score, vector_score, keyword, chunk in scored[:limit]:
            items.append(
                {
                    "id": chunk.id,
                    "source": chunk.source,
                    "title": chunk.title,
                    "content": chunk.content,
                    "tags": chunk.tags,
                    "metadata": chunk.metadata,
                    "score": round(score, 6),
                    "vector_score": round(vector_score, 6),
                    "keyword_score": round(keyword, 6),
                }
            )
        return {"query": query, "total": len(scored), "items": items, "index": self.status()}

    def _load_or_build(self) -> List[KnowledgeChunk]:
        if not self.index_path.exists():
            self.rebuild()
        mtime = self.index_path.stat().st_mtime
        if self._chunks is not None and self._loaded_mtime == mtime:
            return self._chunks
        data = _read_json(self.index_path)
        chunks = []
        for item in data.get("chunks", []):
            chunks.append(
                KnowledgeChunk(
                    id=str(item.get("id") or ""),
                    source=str(item.get("source") or "unknown"),
                    title=str(item.get("title") or ""),
                    content=str(item.get("content") or ""),
                    tags=list(item.get("tags") or []),
                    metadata=dict(item.get("metadata") or {}),
                    vector=list(item.get("vector") or []),
                )
            )
        self._chunks = chunks
        self._loaded_mtime = mtime
        return chunks

    def _collect_chunks(self) -> List[KnowledgeChunk]:
        chunks: List[KnowledgeChunk] = []
        chunks.extend(self._collect_vulnerability_chunks())
        chunks.extend(self._collect_case_chunks("cases.json", source="curated_case"))
        chunks.extend(self._collect_case_chunks("case_index.generated.json", source="generated_case"))
        chunks.extend(self._collect_generated_report_chunks())
        return chunks

    def _collect_vulnerability_chunks(self) -> List[KnowledgeChunk]:
        path = KNOWLEDGE_ROOT / "vulnerability_types.json"
        if not path.exists():
            return []
        payload = _read_json(path)
        items = payload if isinstance(payload, list) else payload.get("items", [])
        chunks = []
        for item in items if isinstance(items, list) else []:
            vul_id = str(item.get("id") or item.get("name_en") or len(chunks))
            title = " / ".join(str(item.get(key) or "") for key in ["name_zh", "name_en"] if item.get(key)) or vul_id
            content = _compact_content(
                [
                    item.get("one_liner"),
                    item.get("mental_model"),
                    item.get("why_it_happens"),
                    item.get("attack_steps"),
                    item.get("trace_signals"),
                    item.get("repair_hints"),
                    item.get("tracepilot_usage"),
                    item.get("practice_sources"),
                ]
            )
            tags = [vul_id, str(item.get("category") or "")]
            chunks.append(
                _make_chunk(
                    chunk_id=f"vulnerability:{vul_id}",
                    source="vulnerability_type",
                    title=title,
                    content=content,
                    tags=[tag for tag in tags if tag],
                    metadata={"type_id": vul_id, "category": item.get("category")},
                )
            )
        return chunks

    def _collect_generated_report_chunks(self) -> List[KnowledgeChunk]:
        path = KNOWLEDGE_ROOT / "generated_reports.json"
        if not path.exists():
            return []
        payload = _read_json(path)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        chunks = []
        for index, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("id") or f"generated_report:{index}")
            title = str(item.get("title") or report_id)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            content = _compact_content(
                [
                    item.get("content"),
                    metadata.get("summary"),
                    metadata.get("dapp_name"),
                    metadata.get("status"),
                ],
                limit=2200,
            )
            tags = [str(tag) for tag in (item.get("tags") or []) if tag]
            chunks.append(
                _make_chunk(
                    chunk_id=f"platform_report:{report_id}",
                    source="platform_report",
                    title=title,
                    content=content,
                    tags=tags,
                    metadata=metadata,
                )
            )
        return chunks

    def _collect_case_chunks(self, file_name: str, source: str) -> List[KnowledgeChunk]:
        path = KNOWLEDGE_ROOT / file_name
        if not path.exists():
            return []
        payload = _read_json(path)
        raw_items = payload.get("cases") if isinstance(payload, dict) and isinstance(payload.get("cases"), list) else None
        if raw_items is None and isinstance(payload, dict):
            raw_items = payload.get("items", [])
        items = raw_items if isinstance(raw_items, list) else []
        external = payload.get("external_classic_cases", []) if isinstance(payload, dict) else []
        if isinstance(external, list):
            items = [*items, *external]
        chunks = []
        for index, item in enumerate(items):
            case_id = str(item.get("case_id") or item.get("id") or item.get("name") or f"{file_name}:{index}")
            title = str(item.get("name") or item.get("title") or case_id)
            content = _compact_content(
                [
                    item.get("learning_summary"),
                    item.get("raw_cause"),
                    item.get("cause"),
                    item.get("root_cause"),
                    item.get("why_selected"),
                    item.get("report"),
                    item.get("attack_steps"),
                    item.get("fix"),
                    item.get("patch"),
                ]
            )
            tags = [str(tag) for tag in (item.get("vulnerability_type_ids") or [])]
            chunks.append(
                _make_chunk(
                    chunk_id=f"{source}:{case_id}",
                    source=source,
                    title=title,
                    content=content,
                    tags=tags,
                    metadata={
                        "case_id": case_id,
                        "platform": item.get("platform"),
                        "root_cause": item.get("root_cause"),
                        "report_link": item.get("report_link") or item.get("link"),
                        "transaction_hashes": item.get("transaction_hashes") or item.get("transaction_hash"),
                    },
                )
            )
        return chunks


_service: Optional[RagService] = None


def get_rag_service() -> RagService:
    global _service
    if _service is None:
        _service = RagService()
    return _service
