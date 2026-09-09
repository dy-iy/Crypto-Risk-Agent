"""Public reference knowledge plus only the caller's generated reports."""
from contextvars import ContextVar
import os
from . import store
from .web.services.rag_service import RagService, _cosine, _keyword_score, _tokens, _vectorize

knowledge_owner: ContextVar[str | None] = ContextVar("attackpilot_owner", default=None)

class ScopedKnowledge:
    def __init__(self):
        self.public = RagService()

    def status(self):
        return self.public.status()

    def rebuild(self):
        return self.public.rebuild()

    def search(self, query, top_k=5, filters=None):
        filters = filters or {}
        result = self.public.search(query, top_k=20, filters=filters)
        items = result["items"]
        owner = knowledge_owner.get() or os.getenv("ATTACKPILOT_OWNER_ID")
        if owner and (not filters.get("source") or filters["source"] == "generated_report"):
            vector, tokens = _vectorize(query), _tokens(query)
            for task in store.list_tasks(owner, True):
                if task["is_demo"] or task["owner_id"] != owner or not task.get("final_report"):
                    continue
                tags = ["generated_report"]
                if filters.get("tag") and filters["tag"] not in tags:
                    continue
                content = task["final_report"][:12000]
                vs = _cosine(vector, _vectorize(content)); ks = _keyword_score(tokens, _tokens(content))
                score = .72 * vs + .28 * ks
                if score > 0:
                    items.append({"id": f"task:{task['task_id']}", "source": "generated_report", "title": task["dapp_name"], "content": content, "tags": tags, "score": score, "vector_score": vs, "keyword_score": ks, "metadata": {"task_id": task["task_id"], "visibility": "private"}})
        items.sort(key=lambda item: item["score"], reverse=True)
        result["total"] = max(result["total"], len(items))
        result["items"] = items[:max(1, min(top_k, 20))]
        return result

_service = None

def get_rag_service():
    global _service
    if _service is None:
        _service = ScopedKnowledge()
    return _service
