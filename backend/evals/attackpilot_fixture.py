"""Export offline HTTP fixtures for the component browser smoke test."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.attackpilot import api, settings, store

async def _export(destination):
    with tempfile.TemporaryDirectory() as root, patch.object(settings, "DATABASE_PATH", Path(root) / "test.sqlite3"), patch.object(settings, "RUNTIME_ROOT", Path(root)):
        store.import_seed(json.loads((settings.PACKAGE_ROOT / "data/demo-seed.json").read_text()))
        app = FastAPI(); app.include_router(api.router)
        async def guest(): yield None
        app.dependency_overrides[api.caller] = guest
        paths = ["capabilities", "dapps", "tasks", "knowledge/vulnerabilities", "knowledge/summary", "knowledge/cases", "rag/status"]
        tasks = store.list_tasks(None, True)
        for task in tasks:
            key = task["task_id"]
            paths.extend(f"tasks/{key}{suffix}" for suffix in ("", "/logs", "/macro-analysis", "/automated-review", "/agent-log-files", "/report-translation"))
            paths.extend(f"task/{key}/log/{event['log_id']}" for event in store.log_page(key, 1000)["events"])
        responses = {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            for path in paths:
                response = await client.get("/api/attackpilot/" + path)
                if response.status_code not in (200, 404):
                    raise RuntimeError(f"Fixture request failed: {path} {response.status_code}")
                responses["/api/attackpilot/" + path] = {"status": response.status_code, "body": response.json()}
            rag = await client.post("/api/attackpilot/rag/search", json={"query": "重入攻击", "top_k": 5})
            if rag.status_code != 200: raise RuntimeError("Public RAG fixture failed")
            responses["/api/attackpilot/rag/search"] = {"status": 200, "body": rag.json()}
        selected = next(task for task in tasks if task["status"] == "completed" and not task["archived"])
        Path(destination).write_text(json.dumps({"responses": responses, "task_id": selected["task_id"]}, ensure_ascii=False))
        print(f"Exported {len(responses)} offline responses; checked {len(tasks)} historical tasks.")

def export(destination):
    asyncio.run(_export(destination))

if __name__ == "__main__": export(sys.argv[1])
