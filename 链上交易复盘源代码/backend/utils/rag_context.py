import json
from typing import Any, Dict, List


def build_rag_query_from_dapp(dapp: Dict[str, Any]) -> str:
    parts = [
        dapp.get("name"),
        dapp.get("cause"),
        dapp.get("root_cause"),
        dapp.get("platform"),
        dapp.get("report"),
    ]
    return " ".join(str(part) for part in parts if part)


def retrieve_rag_context(query: str, top_k: int = 5) -> Dict[str, Any]:
    if not query.strip():
        return {"query": query, "items": [], "total": 0}

    try:
        from app.services.rag_service import get_rag_service

        result = get_rag_service().search(query, top_k=top_k)
    except Exception as exc:
        return {
            "query": query,
            "items": [],
            "total": 0,
            "error": f"RAG retrieval failed: {exc}",
        }

    items: List[Dict[str, Any]] = []
    for item in result.get("items", [])[:top_k]:
        items.append(
            {
                "title": item.get("title"),
                "source": item.get("source"),
                "content": item.get("content"),
                "tags": item.get("tags", [])[:5],
                "score": item.get("score"),
                "metadata": item.get("metadata", {}),
            }
        )

    return {
        "query": query,
        "total": result.get("total", 0),
        "items": items,
    }


def format_rag_context(context: Dict[str, Any], max_chars: int = 4000) -> str:
    if not context or not context.get("items"):
        return "No related knowledge was retrieved."
    text = json.dumps(context, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [RAG context truncated]"
