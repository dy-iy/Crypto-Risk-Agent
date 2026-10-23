from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from app.api.auth import SESSION_COOKIE_NAME
from app.services.auth_service import get_user_by_session
from . import settings, store
from .knowledge import get_rag_service, knowledge_owner
from .privacy import redact, redact_text
from .report_translation import ensure_translation, translation_view
from .schemas import CaseTaskInput, TransactionInput, SearchInput, normalize_modules
from .web import reference_api as reference
from .web.models import AssistantChatRequest, TaskResponse, TxDetectRequest, TxReviewRequest

async def caller(request: Request):
    user = get_user_by_session(request.cookies.get(SESSION_COOKIE_NAME))
    token = knowledge_owner.set(user.id if user else None)
    try:
        yield user
    finally:
        knowledge_owner.reset(token)

def require_user(user):
    if not user:
        raise HTTPException(401, "请先登录后使用链上分析与取证助手")
    return user

def read_task(task_id, user, mutate=False):
    task = store.get_task(task_id)
    if not store.can_read(task, user.id if user else None):
        raise HTTPException(404, "任务不存在或无权访问")
    if mutate:
        require_user(user)
        if task["is_demo"]:
            raise HTTPException(403, "公共历史示例为只读")
    return task

class TaskReader:
    def __init__(self, user):
        self.user = user

    def get_task(self, task_id):
        task = read_task(task_id, self.user)
        return TaskResponse.model_validate(store.public_task(task))

router = APIRouter(prefix="/api/attackpilot", tags=["attackpilot"])
MAX_CURSOR_ID = (1 << 63) - 1

def capabilities():
    missing = [name for name in ("web3", "fastmcp", "networkx", "anytree", "aiofiles") if importlib.util.find_spec(name) is None]
    compiler = settings.COMPILER_ROOT.is_dir() and any(settings.COMPILER_ROOT.glob("solc-linux-amd64-*"))
    node = bool(shutil.which(settings.NODE_PATH))
    node_modules = (settings.PACKAGE_ROOT / "node_modules/solc-typed-ast").exists()
    from .utils.chainlink_config import get_chainlink_config
    try:
        config = get_chainlink_config()
        chainlink = {
            "enabled": config["enabled"], "configuration_valid": True,
            "account_required": False, "wallet_required": False,
            "feeds": {platform: sorted({feed["pair"] for feed in feeds.values()})
                      for platform, feeds in config["feeds"].items()},
            "rpc_max_calls_per_quote": config["max_rpc_calls"],
            "quote_timeout_seconds": config["timeout_seconds"],
            "historical_reference_only": True,
        }
    except ValueError:
        chainlink = {"configuration_valid": False, "reason_code": "invalid_feed_configuration"}
    return {
        "model": {"name": settings.LLM_NAME, "configured": bool(settings.LLM_API_KEY)},
        "chains": {name: {"rpc": bool(settings.JSONRPCS.get(platform)), "explorer": bool(settings.SCAN_APIKEYS.get(platform))} for name, platform in (("ethereum", "Ethereum"), ("bnbchain", "BNBChain"))},
        "tenderly": bool(settings.TENDERLY_API_KEY and settings.ACCOUNT_SLUG and settings.PROJECT_SLUG),
        "chainlink_data_feeds": chainlink,
        "compiler": bool(compiler), "node": node, "node_modules": node_modules,
        "missing_dependencies": missing,
        "note": "配置状态不代表远端服务已验证；历史示例可直接浏览。",
    }

def require_capability(chain: str, modules: list[str], deep=False):
    status = capabilities(); missing = list(status["missing_dependencies"]) if deep else []
    if not status["chains"][chain]["rpc"]: missing.append("链上 RPC")
    if deep:
        if not status["model"]["configured"]: missing.append("DEEPSEEK_API_KEY")
        if not status["chains"][chain]["explorer"]: missing.append("区块浏览器接口")
        if not status["node"] or not status["node_modules"]: missing.append("Node.js 编译依赖")
        if not status["compiler"]: missing.append("Solidity 编译器")
        # Original dynamic trace loader requires Tenderly, even before patch replay.
        if not status["tenderly"]: missing.append("Tenderly")
    if missing:
        raise HTTPException(503, "分析环境尚未就绪：" + "、".join(missing))

def hashes(payload: TransactionInput):
    values = payload.tx_hashes or ([payload.tx_hash] if payload.tx_hash else [])
    if not 1 <= len(values) <= 50:
        raise HTTPException(422, "请提交 1 至 50 笔交易")
    valid, invalid = reference._normalize_tx_hashes(values, max_count=50)
    if not valid:
        raise HTTPException(422, "交易 Hash 应为 0x 开头的 64 位十六进制字符串")
    return valid, invalid

@router.get("/capabilities")
def get_capabilities():
    return capabilities()

@router.get("/dapps")
async def dapps():
    return await reference.list_dapps()

@router.post("/tx-review")
async def review(payload: TransactionInput, user=Depends(caller)):
    require_user(user); valid, invalid = hashes(payload)
    if invalid or len(valid) != 1:
        raise HTTPException(422, "单笔审查只接受一个有效交易 Hash")
    require_capability(payload.chain, [])
    return redact((await reference.review_transaction_hash(TxReviewRequest(tx_hash=valid[0], chain=payload.chain))).model_dump())

@router.post("/tx-detect")
async def detect(payload: TransactionInput, user=Depends(caller)):
    require_user(user); valid, invalid = hashes(payload)
    require_capability(payload.chain, payload.modules)
    result = await reference.detect_transaction_set(TxDetectRequest(tx_hashes=valid, chain=payload.chain, modules=normalize_modules(payload.modules)))
    result.invalid_hashes = invalid
    result.input_count = len(payload.tx_hashes or [payload.tx_hash])
    return redact(result.model_dump())

@router.post("/tx-review/deep-analysis", status_code=201)
async def deep_analysis(payload: TransactionInput, user=Depends(caller)):
    require_user(user); valid, invalid = hashes(payload)
    if invalid:
        raise HTTPException(422, "请移除无效交易 Hash 后再启动深度分析")
    modules = normalize_modules(payload.modules)
    require_capability(payload.chain, modules, deep=True)
    data = reference._build_adhoc_dapp_payload(valid[0], payload.chain, valid, modules)
    return redact(store.public_task(store.create_task(user.id, data)))

@router.post("/tasks", status_code=201)
async def create_case(payload: CaseTaskInput, user=Depends(caller)):
    require_user(user)
    try: modules = normalize_modules(payload.modules)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    data = None
    for path in (settings.PACKAGE_ROOT / "dataset/raw").glob("*.json"):
        try:
            candidate = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(candidate, dict) and candidate.get("name") == payload.dapp_name:
            data = candidate; break
    if not data:
        raise HTTPException(404, "未找到该案例")
    txs = data.get("transaction_hash") or []
    if not isinstance(txs, list) or not 1 <= len(txs) <= 50:
        raise HTTPException(422, "当前案例须包含 1 至 50 笔交易，可在交易审查中选择交易后分析")
    valid, invalid = reference._normalize_tx_hashes(txs, max_count=50)
    if invalid or not valid:
        raise HTTPException(422, "当前案例包含无效交易 Hash")
    data["transaction_hash"] = valid
    chain = {"Ethereum": "ethereum", "BNBChain": "bnbchain", "BSC": "bnbchain"}.get(data.get("platform"))
    if not chain:
        raise HTTPException(422, "当前仅支持 Ethereum 和 BNB Chain")
    require_capability(chain, modules, deep=True)
    data["platform"] = "Ethereum" if chain == "ethereum" else "BNBChain"
    data["enabled_modules"] = modules
    return redact(store.public_task(store.create_task(user.id, data)))

@router.get("/tasks")
def tasks(include_archived: bool = False, user=Depends(caller)):
    return redact([store.public_task(task) for task in store.list_tasks(user.id if user else None, include_archived)])

@router.get("/tasks/{task_id}")
def task_detail(task_id: str, user=Depends(caller)):
    return redact(store.public_task(read_task(task_id, user)))

@router.get("/tasks/{task_id}/report-translation")
def report_translation(task_id: str, user=Depends(caller)):
    return translation_view(read_task(task_id, user))

@router.post("/tasks/{task_id}/report-translation")
async def create_report_translation(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user)
    require_user(user)
    # This creates a language derivative; public historical evidence stays read-only.
    return await ensure_translation(task)

@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user, True)
    if task["status"] in store.TERMINAL:
        raise HTTPException(409, "任务已经结束")
    if not store.transition(task_id, "cancelled", error="用户取消任务"):
        raise HTTPException(409, "任务已经结束")
    return {"status": "cancelled"}

@router.post("/tasks/{task_id}/archive")
def archive(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user, True)
    if task["status"] not in store.TERMINAL: raise HTTPException(409, "请先结束任务")
    store.archive(task_id, True); return {"archived": True}

@router.post("/tasks/{task_id}/unarchive")
def unarchive(task_id: str, user=Depends(caller)):
    read_task(task_id, user, True)
    store.archive(task_id, False); return {"archived": False}

@router.delete("/tasks/{task_id}")
def delete(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user, True)
    if task["status"] not in store.TERMINAL: raise HTTPException(409, "请先结束任务")
    store.delete_task(task_id)
    shutil.rmtree(store.task_dir(task_id), ignore_errors=True)
    return {"deleted": True}

@router.get("/tasks/{task_id}/logs")
def logs(task_id: str, limit: int = Query(200, ge=1, le=1000), before_id: int | None = Query(None, ge=0, le=MAX_CURSOR_ID), after_id: int | None = Query(None, ge=0, le=MAX_CURSOR_ID), user=Depends(caller)):
    read_task(task_id, user)
    return redact(store.log_page(task_id, limit, before_id, after_id))

@router.get("/task/{task_id}/log/{log_id}")
def full_log(task_id: str, log_id: str, user=Depends(caller)):
    read_task(task_id, user)
    content = store.full_log(task_id, log_id)
    if content is None: raise HTTPException(404, "日志不存在")
    return {"content": redact_text(content), "source": "database"}

@router.get("/tasks/{task_id}/events")
async def events(task_id: str, request: Request, after_id: int = Query(0, ge=0, le=MAX_CURSOR_ID), user=Depends(caller)):
    task = read_task(task_id, user)
    try:
        previous_id = int(request.headers.get("last-event-id", "0"))
        if not 0 <= previous_id <= MAX_CURSOR_ID:
            raise ValueError
        cursor = max(after_id, previous_id)
    except ValueError: raise HTTPException(400, "无效事件编号")
    session = request.cookies.get(SESSION_COOKIE_NAME)
    async def stream():
        nonlocal cursor
        yield "data: " + json.dumps({"type": "CONNECTED", "task_id": task_id}) + "\n\n"
        heartbeat = 0
        while not await request.is_disconnected():
            if not task["is_demo"]:
                current_user = get_user_by_session(session)
                if not current_user or current_user.id != task["owner_id"]: break
            current = store.get_task(task_id)
            if not current: break
            batch = store.events_after(task_id, cursor)
            for event in batch:
                cursor = event["id"]
                payload = event['payload']
                if payload.get("type") == "TASK_FINAL":
                    # Evidence revisions append another final event. Clients
                    # close at their first final, so deliver the current saved
                    # result even when resuming an older event history.
                    latest = store.get_task(task_id)
                    if not latest:
                        return
                    payload = {"type": "TASK_FINAL", **store.public_task(latest)}
                    yield f"id: {cursor}\ndata: {json.dumps(redact(payload), ensure_ascii=False)}\n\n"
                    return
                yield f"id: {cursor}\ndata: {json.dumps(redact(payload), ensure_ascii=False)}\n\n"
            if current["status"] in store.TERMINAL and not batch:
                yield "data: " + json.dumps({"type": "TASK_FINAL", **redact(store.public_task(current))}, ensure_ascii=False) + "\n\n"
                break
            if heartbeat % 15 == 0: yield ": heartbeat\n\n"
            heartbeat += 1
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})

@router.get("/tasks/{task_id}/macro-analysis")
def macro(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user)
    return redact(reference._load_macro_analysis_payload(TaskResponse.model_validate(store.public_task(task))))

@router.get("/tasks/{task_id}/automated-review")
def automated_review(task_id: str, user=Depends(caller)):
    task = TaskResponse.model_validate(store.public_task(read_task(task_id, user)))
    try: macro_data = reference._load_macro_analysis_payload(task)
    except HTTPException as exc:
        if exc.status_code != 404: raise
        macro_data = None
    return redact(reference.build_automated_review(task, store.log_page(task_id, 5000)["events"], macro_data))

@router.get("/tasks/{task_id}/agent-log-files")
def agent_files(task_id: str, user=Depends(caller)):
    task = read_task(task_id, user)
    root = store.task_dir(task_id) / "agent-logs"
    files = []
    for path in root.rglob("*.log") if root.exists() else []:
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        files.append({"id": reference._b64_encode(relative), "name": path.name, "agent": path.stem, "size": path.stat().st_size, "modified_at": store.now()})
    return {"task_id": task_id, "dapp_name": task["dapp_name"], "log_dir": "agent-logs", "files": files}

@router.get("/tasks/{task_id}/agent-log-files/{file_id}")
def agent_file(task_id: str, file_id: str, max_bytes: int = Query(2_000_000, ge=1, le=2_000_000), user=Depends(caller)):
    task = read_task(task_id, user); root = store.task_dir(task_id) / "agent-logs"
    try:
        path = (root / reference._b64_decode(file_id)).resolve()
        path.relative_to(root.resolve())
    except (ValueError, UnicodeError): raise HTTPException(400, "无效日志文件")
    if not path.is_file() or path.suffix != ".log": raise HTTPException(404, "日志文件不存在")
    with path.open("rb") as stream: raw = stream.read(max_bytes)
    return {"task_id": task_id, "dapp_name": task["dapp_name"], "id": file_id, "name": path.name, "agent": path.stem, "content": redact_text(raw.decode("utf-8", errors="replace")), "size": path.stat().st_size, "truncated": path.stat().st_size > max_bytes, "modified_at": store.now()}

@router.get("/knowledge/vulnerabilities")
async def vulnerabilities(): return await reference.list_vulnerability_types()

@router.get("/knowledge/vulnerabilities/{type_id}")
async def vulnerability(type_id: str): return await reference.get_vulnerability_type(type_id)

@router.get("/knowledge/cases")
async def cases(source: str = Query("generated", pattern="^(curated|generated)$"), type_id: str | None = None, q: str | None = None):
    return await reference.list_knowledge_cases(source, type_id, q)

@router.get("/knowledge/cases/{case_id}")
async def case(case_id: str, source: str = Query("generated", pattern="^(curated|generated)$")):
    return await reference.get_knowledge_case(case_id, source)

@router.get("/knowledge/summary")
async def summary(): return await reference.get_knowledge_summary()

@router.get("/rag/status")
def rag_status(): return get_rag_service().status()

@router.post("/rag/search")
def rag_search(payload: SearchInput, user=Depends(caller)):
    return redact(get_rag_service().search(payload.query, payload.top_k, payload.filters))

@router.post("/rag/rebuild")
def rebuild(user=Depends(caller)):
    if not require_user(user).is_admin: raise HTTPException(403, "仅管理员可重建公共索引")
    return get_rag_service().rebuild()

@router.post("/assistant/chat")
async def assistant(payload: AssistantChatRequest, user=Depends(caller)):
    require_user(user)
    if not payload.question.strip():
        raise HTTPException(422, "请输入问题")
    if payload.task_id: read_task(payload.task_id, user)
    if not settings.LLM_API_KEY: raise HTTPException(503, "请在后端 .env 配置 DEEPSEEK_API_KEY")
    return redact((await reference.chat_with_assistant(payload, TaskReader(user))).model_dump())
