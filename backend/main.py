import json

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agents.chat_agent import run_chat_agent
from app.api.risk_ranking import router as risk_ranking_router
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


@app.post("/api/risk-assistant", response_model=RiskAssistantResponse)
def risk_assistant(request: RiskAssistantRequest) -> RiskAssistantResponse:
    try:
        answer = answer_risk_assistant(request.question, request.context)
        return RiskAssistantResponse(answer=answer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk assistant failed: {exc}") from exc


@app.post("/api/risk-assistant/stream")
async def risk_assistant_stream(request: RiskAssistantRequest) -> StreamingResponse:
    try:
        async def event_stream():
            async for chunk in stream_risk_assistant_answer(request.question, request.context):
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk assistant failed: {exc}") from exc


@app.post("/analyze", response_model=ChatResponse)
def analyze(request: ChatRequest | None = Body(default=None)) -> ChatResponse:
    if request is None:
        request = ChatRequest(message="某 DeFi 项目疑似被攻击，资金池出现异常大额转出，官方尚未发布公告。")
    return chat(request)
