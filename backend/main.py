import json
from queue import Queue
from threading import Thread

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents.chat_agent import run_chat_agent, run_chat_agent_with_progress
from app.api.portfolio import router as portfolio_router
from app.api.risk_ranking import router as risk_ranking_router
from app.api.sim import router as sim_router
from app.schemas import (
    ChatRequest,
    ChatResponse,
    RiskAssistantRequest,
    RiskAssistantResponse,
    RiskReport,
)
from app.services.risk_assistant_service import answer_risk_assistant, stream_risk_assistant_answer


app = FastAPI(title="CryptoRisk Agent Backend")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://kassa-wiki.top",
    "https://kassa-wiki.top",
    "http://www.kassa-wiki.top",
    "https://www.kassa-wiki.top",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk_ranking_router)
app.include_router(sim_router)
app.include_router(portfolio_router)


@app.get("/")
def root():
    return {"message": "CryptoRisk Agent Backend is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        final_report = run_chat_agent(request.message)
        return ChatResponse(data=RiskReport.model_validate(final_report))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {exc}") from exc


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    def event_stream():
        queue: Queue[tuple[str, dict[str, object]]] = Queue()

        def worker() -> None:
            try:
                report = run_chat_agent_with_progress(
                    request.message,
                    progress_callback=lambda event: queue.put(("progress", event)),
                )
                payload = ChatResponse(data=RiskReport.model_validate(report)).model_dump()
                queue.put(("result", payload))
            except Exception as exc:
                queue.put(("error", {"detail": f"Agent workflow failed: {exc}"}))

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
def risk_assistant(request: RiskAssistantRequest) -> RiskAssistantResponse:
    try:
        question = normalize_risk_assistant_question(request)
        answer = answer_risk_assistant(
            question,
            request.context,
            selected_text=request.selected_text,
            user_question=request.user_question,
        )
        return RiskAssistantResponse(answer=answer)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk assistant failed: {exc}") from exc


@app.post("/api/risk-assistant/stream")
async def risk_assistant_stream(request: RiskAssistantRequest) -> StreamingResponse:
    try:
        question = normalize_risk_assistant_question(request)

        async def event_stream():
            async for chunk in stream_risk_assistant_answer(
                question,
                request.context,
                selected_text=request.selected_text,
                user_question=request.user_question,
            ):
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"

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
        raise HTTPException(status_code=500, detail=f"Risk assistant failed: {exc}") from exc


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
    return chat(request)
