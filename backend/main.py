from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.chat_agent import run_chat_agent
from app.api.risk_ranking import router as risk_ranking_router
from app.schemas import ChatRequest, ChatResponse, RiskReport


app = FastAPI(title="CryptoRisk Agent Backend")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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


@app.post("/analyze", response_model=ChatResponse)
def analyze(request: ChatRequest | None = Body(default=None)) -> ChatResponse:
    if request is None:
        request = ChatRequest(message="某 DeFi 项目疑似被攻击，资金池出现异常大额转出，官方尚未发布公告。")
    return chat(request)
