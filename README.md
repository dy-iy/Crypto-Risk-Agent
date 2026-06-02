# CryptoRisk Agent

CryptoRisk Agent 是一个面向加密货币金融风控场景的 Multi-Agent 系统。前端以聊天窗口和风险看板呈现，后端通过 FastAPI、LangChain、LangGraph 和 DeepSeek API 对新闻、公告、项目事件、交易所异常、链上安全事件等内容进行风险识别、分类、评分、证据抽取、影响分析和处置建议生成。

> 本项目用于风险研判、安全分析和黑客松展示，不构成投资建议。



## 核心能力

- 聊天式风控分析：输入新闻、公告、链上安全线索或项目事件，生成结构化风险报告。
- 多 Agent 工作流：完成风险信号扫描、风险类型分支分析、冲突校验、影响对象分析和建议生成。
- 新闻风险排行：聚合本地新闻数据和增量更新结果，输出高风险新闻榜单。
- 币种风险排行：按币种维度汇总风险事件、热度、主风险类型和关联新闻。
- 个人资产风险：根据用户自选资产、持仓敞口和风险事件生成组合影响评分。
- 日报与收藏：支持用户登录、收藏风险事件、同步分析报告和生成个人风险日报。
- 模拟交易：基于本地 K 线和风险事件进行风险驱动的交易演示。

## 技术栈

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、Python、Pydantic
- Agent：LangChain、LangGraph
- 模型 API：DeepSeek API
- 默认模型：`deepseek-v4-pro`
- 数据：本地新闻 CSV/JSON、SQLite 用户数据、运行态 JSON 缓存

## 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── agents/      # Chat Agent、Ranking Agent、Daily Report Agent
│   │   ├── api/         # FastAPI 路由
│   │   ├── data/        # 演示新闻数据和更新脚本
│   │   ├── services/    # 鉴权、排行榜、组合风险、日报、数据加载
│   │   └── tools/       # 风控规则和 Agent 工具
│   ├── evals/           # 后端回归与风控评测用例
│   ├── main.py          # FastAPI 入口
│   └── requirements.txt
├── frontend/
│   ├── app/             # Next.js App Router 页面
│   ├── components/      # 风控看板、详情页、组合雷达和模拟交易
│   ├── lib/             # 前端 API 与本地缓存封装
│   └── package.json
├── data/sim/klines/     # 模拟交易本地 K 线种子数据
├── docs/                # 项目说明、流程图和技术路线
├── skills/              # crypto-risk-agent Skill
└── README.md
```

## 环境变量

后端读取 `.env` 或环境变量。

```env
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=30

AUTH_PASSWORD_PEPPER=建议设置一段随机强密钥
CORS_ALLOWED_ORIGINS=https://kassa-wiki.top,https://www.kassa-wiki.top
ALLOW_LOCAL_CORS=0
ALLOW_USER_ID_QUERY_OVERRIDE=0
```

可选新闻源代理：

```env
BINANCE_PROXY_URL=
BINANCE_HTTP_PROXY=
BINANCE_HTTPS_PROXY=
```

## 数据边界

保留在仓库中的演示数据：

- `backend/app/data/mastered_news.csv`
- `backend/app/data/raw_news.csv`
- `backend/app/data/scored_news.json`
- `data/sim/klines/*.json`

运行时生成且已加入 `.gitignore` 的数据：

- `backend/app/data/auth.sqlite3`
- `backend/app/data/analysis_reports.sqlite3`
- `backend/app/data/daily_reports/`
- `backend/app/data/portfolio_state.json`
- `backend/app/data/update_jobs.json`
- `backend/app/data/*.bak_*`

## API 概览

- `POST /api/chat`：提交文本并生成风控分析报告。
- `POST /api/chat/stream`：流式返回 Chat Agent 进度和最终报告。
- `POST /api/risk-assistant/stream`：围绕页面上下文或选中文本进行风险问答。
- `GET /api/rankings/overview`：获取风险看板概览。
- `GET /api/rankings/news`：获取新闻风险榜。
- `GET /api/rankings/news/{news_id}`：获取新闻详情。
- `GET /api/rankings/coins`：获取币种风险榜。
- `GET /api/rankings/coins/{symbol}`：获取币种详情。
- `POST /api/rankings/update-news/jobs`：创建新闻更新任务。
- `GET /api/portfolio/impact`：获取个人组合影响评分。
- `GET /api/user-assets`：获取当前用户资产列表。
- `GET /api/daily-report`：获取个人风险日报。
- `POST /api/daily-report/generate`：生成个人风险日报。
- `GET /api/sim/state`：获取模拟交易状态。

## 本地检查

本项目收尾时不要执行服务启动、前端开发服务、前端构建或 PM2 命令。允许使用以下静态检查和回归测试：

```bash
cd backend
python -m pytest evals
```

```bash
cd frontend
npm run lint
```

## 部署备注

- 线上入口统一使用 `https://kassa-wiki.top`。
- 前端请求必须保持 `/api/...` 相对路径。
- 后端默认 CORS 只允许公网域名；如需本地浏览器直连调试，显式设置 `ALLOW_LOCAL_CORS=1`。
- 用户身份依赖 `cryptorisk_session` HttpOnly Cookie。
- `ALLOW_USER_ID_QUERY_OVERRIDE` 默认关闭，避免通过查询参数访问或修改其他用户的资产数据。

## Skill

仓库内置 `skills/crypto-risk-agent/`，可供支持 Skill 的 Agent 客户端读取项目 API 契约和调用脚本。脚本默认面向公开站点 `/api` 契约，适合快速演示风控能力。
