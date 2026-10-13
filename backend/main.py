import json
import logging
import os
import re
import time
import uuid
from queue import Queue
from threading import Thread

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.account import router as account_router
from app.attackpilot.api import router as attackpilot_router
from app.api.analysis_reports import router as analysis_reports_router
from app.api.auth import SESSION_COOKIE_NAME, router as auth_router
from app.api.coin_library import router as coin_library_router
from app.api.daily_report import router as daily_report_router
from app.api.favorites import router as favorites_router
from app.api.feishu import router as feishu_router
from app.agents.chat_agent import run_chat_agent, run_chat_agent_with_progress
from app.api.portfolio import router as portfolio_router
from app.api.risk_ranking import router as risk_ranking_router
from app.api.market import router as market_router
from app.api.follows import router as follows_router
from app.services.market_data_service import close_market_client
from app.api.system import router as system_router
from app.api.user_assets import router as user_assets_router
from app.schemas import (
    ChatRequest,
    ChatResponse,
    RiskAssistantRequest,
    RiskAssistantResponse,
    RiskReport,
)
from app.services.risk_assistant_service import (
    answer_risk_assistant,
    stream_risk_assistant_answer,
)
from app.services.analysis_audit_service import (
    record_chat_analysis_error,
    record_chat_analysis_success,
    record_risk_assistant_error,
    record_risk_assistant_success,
)
from app.services.auth_service import get_user_by_session
from app.services.csrf_service import csrf_request_allowed
from app.services.daily_scheduler_service import start_daily_scheduler_thread, stop_daily_scheduler_thread
from app.services.error_response_service import (
    PUBLIC_AGENT_ERROR_DETAIL,
    PUBLIC_INTERNAL_ERROR_DETAIL,
    PUBLIC_RISK_ASSISTANT_ERROR_DETAIL,
    public_error_payload,
)
from app.services.rate_limit_service import check_rate_limit
from app.services.request_body_limit_service import max_request_body_bytes, request_body_exceeds_limit
from app.services.request_security_service import request_client_identity
from app.services.report_response_service import sanitize_risk_report_for_public_api


logger = logging.getLogger("cryptorisk.api")
app = FastAPI(title="CryptoRisk Agent Backend")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic's raw input may contain non-JSON floats or sensitive form fields.
    # Preserve the usual detail list without echoing input or exception objects.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]})

DEFAULT_CORS_ORIGINS = [
    "https://crypto.kassa-wiki.top",
    "https://kassa-wiki.top",
    "https://www.kassa-wiki.top",
]
LOCAL_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    origins = [item.strip() for item in raw.split(",") if item.strip()] if raw else list(DEFAULT_CORS_ORIGINS)
    if os.getenv("ALLOW_LOCAL_CORS") == "1":
        origins.extend(LOCAL_CORS_ORIGINS)
    return list(dict.fromkeys(origins))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def operational_headers_middleware(request: Request, call_next):
    candidate_id = request.headers.get("x-request-id", "")
    request_id = candidate_id if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", candidate_id) else uuid.uuid4().hex
    start = time.perf_counter()
    max_body_bytes = max_request_body_bytes()
    if await request_body_exceeds_limit(request, max_body_bytes):
        response = JSONResponse(
            status_code=413,
            content={
                "detail": "Request body too large.",
                "max_request_body_bytes": max_body_bytes,
            },
        )
    elif not _csrf_request_allowed(request):
        response = JSONResponse(
            status_code=403,
            content={
                "detail": "Missing CSRF protection header for session-authenticated mutation.",
            },
        )
    else:
        rate_limit_decision = check_rate_limit(
            identity=_request_identity(request),
            path=request.url.path,
            method=request.method,
        )
        if not rate_limit_decision.allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please retry later.",
                    "rate_limit": {
                        "rule": rate_limit_decision.rule_name,
                        "limit": rate_limit_decision.limit,
                        "retry_after_seconds": rate_limit_decision.retry_after_seconds,
                    },
                },
                headers={"Retry-After": str(rate_limit_decision.retry_after_seconds)},
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("request_failed", extra={"request_id": request_id, "path": request.url.path})
                response = JSONResponse(
                    status_code=500,
                    content={
                        "detail": PUBLIC_INTERNAL_ERROR_DETAIL,
                        "request_id": request_id,
                    },
                )
            if rate_limit_decision.rule_name:
                response.headers["X-RateLimit-Limit"] = str(rate_limit_decision.limit)
                response.headers["X-RateLimit-Remaining"] = str(rate_limit_decision.remaining)
                response.headers["X-RateLimit-Reset"] = str(rate_limit_decision.reset_seconds)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 1),
        },
    )
    return response


def _request_identity(request: Request) -> str:
    client_host = request.client.host if request.client else ""
    return request_client_identity(client_host, request.headers)


def _csrf_request_allowed(request: Request) -> bool:
    return csrf_request_allowed(
        method=request.method,
        cookies=request.cookies,
        headers=request.headers,
        session_cookie_name=SESSION_COOKIE_NAME,
    )


def _session_user_id(request: Request | None) -> str:
    if request is None:
        return ""
    try:
        user = get_user_by_session(request.cookies.get(SESSION_COOKIE_NAME))
    except Exception:
        return ""
    return user.id if user else ""


def _public_chat_response(report: dict[str, object]) -> ChatResponse:
    public_report = sanitize_risk_report_for_public_api(report)
    return ChatResponse(data=RiskReport.model_validate(public_report))

app.include_router(risk_ranking_router)
app.include_router(analysis_reports_router)
app.include_router(coin_library_router)
app.include_router(market_router)
app.include_router(follows_router)
app.include_router(system_router)
app.include_router(portfolio_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(favorites_router)
app.include_router(daily_report_router)
app.include_router(user_assets_router)
app.include_router(feishu_router)
app.include_router(attackpilot_router)


@app.on_event("startup")
async def start_attackpilot() -> None:
    from app.attackpilot import settings, store
    from app.attackpilot.manager import manager
    seed = settings.PACKAGE_ROOT / "data/demo-seed.json"
    if seed.exists():
        store.import_seed(json.loads(seed.read_text()))
    await manager.start()


@app.on_event("shutdown")
async def stop_attackpilot() -> None:
    from app.attackpilot.manager import manager
    await manager.stop()


@app.on_event("startup")
def start_background_services() -> None:
    start_daily_scheduler_thread()


@app.on_event("shutdown")
def stop_background_services() -> None:
    close_market_client()
    stop_daily_scheduler_thread()


@app.get("/")
def root():
    return {"message": "CryptoRisk Agent Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/health")
def api_health():
    return health()


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    job_id = f"chat-{uuid.uuid4().hex}"
    start = time.perf_counter()
    user_id = _session_user_id(http_request)
    try:
        final_report = run_chat_agent(request.message)
        record_chat_analysis_success(
            job_id=job_id,
            input_text=request.message,
            report=final_report,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/api/chat",
            user_id=user_id,
        )
        return _public_chat_response(final_report)
    except Exception as exc:
        record_chat_analysis_error(
            job_id=job_id,
            input_text=request.message,
            error=exc,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/api/chat",
            user_id=user_id,
        )
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_AGENT_ERROR_DETAIL,
            headers={"X-CryptoRisk-Job-ID": job_id},
        ) from exc


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest, http_request: Request) -> StreamingResponse:
    job_id = f"chat-{uuid.uuid4().hex}"
    user_id = _session_user_id(http_request)

    def event_stream():
        queue: Queue[tuple[str, dict[str, object]]] = Queue()

        def worker() -> None:
            start = time.perf_counter()
            try:
                report = run_chat_agent_with_progress(
                    request.message,
                    progress_callback=lambda event: queue.put(("progress", event)),
                )
                record_chat_analysis_success(
                    job_id=job_id,
                    input_text=request.message,
                    report=report,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    endpoint="/api/chat/stream",
                    streaming=True,
                    user_id=user_id,
                )
                payload = _public_chat_response(report).model_dump()
                queue.put(("result", payload))
            except Exception as exc:
                record_chat_analysis_error(
                    job_id=job_id,
                    input_text=request.message,
                    error=exc,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    endpoint="/api/chat/stream",
                    streaming=True,
                    user_id=user_id,
                )
                queue.put(("error", public_error_payload(PUBLIC_AGENT_ERROR_DETAIL, job_id)))

        Thread(target=worker, daemon=True).start()

        while True:
            event_name, payload = queue.get()
            yield f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if event_name in {"result", "error"}:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/risk-assistant", response_model=RiskAssistantResponse)
def risk_assistant(request: RiskAssistantRequest, http_request: Request) -> RiskAssistantResponse:
    job_id = f"risk-assistant-{uuid.uuid4().hex}"
    start = time.perf_counter()
    user_id = _session_user_id(http_request)
    try:
        question = normalize_risk_assistant_question(request)
        answer = answer_risk_assistant(
            question,
            request.context,
            selected_text=request.selected_text,
            user_question=request.user_question,
        )
        record_risk_assistant_success(
            job_id=job_id,
            question=question,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/api/risk-assistant",
            user_id=user_id,
            answer_chars=len(answer or ""),
        )
        return RiskAssistantResponse(answer=answer)
    except HTTPException:
        raise
    except Exception as exc:
        question = (request.user_question or request.question or request.selected_text or "").strip()
        record_risk_assistant_error(
            job_id=job_id,
            question=question,
            error=exc,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/api/risk-assistant",
            user_id=user_id,
        )
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_RISK_ASSISTANT_ERROR_DETAIL,
            headers={"X-CryptoRisk-Job-ID": job_id},
        ) from exc


@app.post("/api/risk-assistant/stream")
async def risk_assistant_stream(request: RiskAssistantRequest, http_request: Request) -> StreamingResponse:
    job_id = f"risk-assistant-{uuid.uuid4().hex}"
    user_id = _session_user_id(http_request)
    try:
        question = normalize_risk_assistant_question(request)

        async def event_stream():
            start = time.perf_counter()
            answer_chars = 0
            try:
                async for chunk in stream_risk_assistant_answer(
                    question,
                    request.context,
                    selected_text=request.selected_text,
                    user_question=request.user_question,
                ):
                    answer_chars += len(chunk or "")
                    yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                record_risk_assistant_success(
                    job_id=job_id,
                    question=question,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    endpoint="/api/risk-assistant/stream",
                    streaming=True,
                    user_id=user_id,
                    answer_chars=answer_chars,
                )
                yield "event: done\ndata: {}\n\n"
            except Exception as exc:
                record_risk_assistant_error(
                    job_id=job_id,
                    question=question,
                    error=exc,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    endpoint="/api/risk-assistant/stream",
                    streaming=True,
                    user_id=user_id,
                )
                yield (
                    "event: error\n"
                    f"data: {json.dumps(public_error_payload(PUBLIC_RISK_ASSISTANT_ERROR_DETAIL, job_id), ensure_ascii=False)}\n\n"
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_RISK_ASSISTANT_ERROR_DETAIL,
            headers={"X-CryptoRisk-Job-ID": job_id},
        ) from exc


def normalize_risk_assistant_question(request: RiskAssistantRequest) -> str:
    question = (request.user_question or request.question or "").strip()
    if not question and request.selected_text:
        return "请解释这段内容"
    if not question:
        raise HTTPException(status_code=422, detail="question or user_question is required")
    return question


@app.post("/analyze", response_model=ChatResponse)
def analyze(request: ChatRequest | None = Body(default=None)) -> ChatResponse:
    if request is None:
        request = ChatRequest(message="某 DeFi 项目疑似被攻击，资金池出现异常大额转出，官方尚未发布公告。")
    job_id = f"chat-{uuid.uuid4().hex}"
    start = time.perf_counter()
    try:
        final_report = run_chat_agent(request.message)
        record_chat_analysis_success(
            job_id=job_id,
            input_text=request.message,
            report=final_report,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/analyze",
        )
        return _public_chat_response(final_report)
    except Exception as exc:
        record_chat_analysis_error(
            job_id=job_id,
            input_text=request.message,
            error=exc,
            duration_ms=(time.perf_counter() - start) * 1000,
            endpoint="/analyze",
        )
        raise HTTPException(
            status_code=500,
            detail=PUBLIC_AGENT_ERROR_DETAIL,
            headers={"X-CryptoRisk-Job-ID": job_id},
        ) from exc
