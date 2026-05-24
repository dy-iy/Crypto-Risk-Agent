# CryptoRisk Agent

加密货币金融风控 Multi-Agent 系统。项目面向黑客松金融风控赛道，使用聊天窗口和排行榜页面，对加密货币新闻、公告、项目事件、交易所异常、链上安全事件等内容进行风险识别、分类、评分、证据抽取、影响分析和处置建议生成。

## 功能

- 聊天式事件风险分析：输入新闻、公告、链上事件或异常描述，输出结构化风控报告。
- 新闻风险排行榜：基于 Binance Square 新闻和本地新闻集生成新闻风险 Top榜。
- 币种风险排行榜：聚合相关新闻中的币种实体，生成币种维度风险排行。
- 今日新闻更新：抓取近 7 天新闻，去重入库，增量触发 Agent 标注。
- 风控辅助问答：支持结合当前页面上下文进行流式问答。
- 降级运行：DeepSeek 或新闻源不可用时，系统会尽量使用规则兜底和本地数据保持演示可用。

## 技术栈

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、Python、Pydantic
- Agent 工作流：LangChain、LangGraph 风格的多节点风控流程
- 模型 API：DeepSeek API
- 模型：`deepseek-v4-pro`

## 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── agents/          # 聊天 Agent 与排行榜 Agent
│   │   ├── api/             # FastAPI 路由
│   │   ├── data/            # 新闻数据、评分缓存、更新脚本
│   │   ├── prompts/         # 风控提示词
│   │   ├── services/        # LLM、数据加载、聚合、问答服务
│   │   └── tools/           # Agent 工具节点
│   ├── main.py              # FastAPI 入口
│   └── requirements.txt
├── frontend/
│   ├── app/                 # Next.js App Router 页面
│   ├── components/          # 风控仪表盘与详情页组件
│   └── lib/api.ts           # 前端 API 封装
└── README.md
```

## 环境变量

后端读取 `backend/app/.env` 或 `backend/.env`：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=30
```

可选配置：

```bash
CRYPTO_RISK_AGENT_OFFLINE=1
RANKING_AGENT_CONCURRENCY=6
BINANCE_NEWS_URL=https://www.binance.com/bapi/composite/v4/friendly/pgc/feed/news/list
BINANCE_NEWS_PAGE_URL=https://www.binance.com/zh-CN/square/news/all
BINANCE_PROXY_URL=http://proxy.example:7890
```

`.env` 文件包含密钥，禁止提交到 Git。

## 本地服务约定

- 前端 Next.js：`127.0.0.1:3000`
- 后端 FastAPI：`127.0.0.1:8001`
- 公网访问：`https://kassa-wiki.top`

Nginx 转发：

```text
/      -> http://127.0.0.1:3000
/api/  -> http://127.0.0.1:8001
```

前端请求约束：

- 前端代码只能请求 `/api/xxx`
- 前端代码禁止硬编码 `localhost`
- 前端代码禁止硬编码 `127.0.0.1`
- 前端代码禁止硬编码 `8000`、`8001`、`8002`

## 常用命令

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8001 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

项目部署时前端应通过相对路径 `/api/...` 访问后端，由 Nginx 负责代理。

## API 概览

基础接口：

- `GET /health`：后端健康检查
- `POST /api/chat`：聊天式风控分析
- `POST /api/risk-assistant`：上下文问答
- `POST /api/risk-assistant/stream`：流式上下文问答

排行榜接口：

- `GET /api/rankings/overview?date=24h`
- `GET /api/rankings/news?date=7d&limit=10`
- `GET /api/rankings/news/{news_id}`
- `GET /api/rankings/coins?date=7d&limit=10`
- `GET /api/rankings/coins/{symbol}`

新闻更新接口：

- `POST /api/rankings/update-news/jobs`：启动异步新闻更新任务
- `GET /api/rankings/update-news/jobs/{job_id}`：查询任务进度
- `POST /api/rankings/update-news`：同步更新新闻，主要用于调试

## 数据文件

- `backend/app/data/mastered_news.csv`：主新闻集
- `backend/app/data/raw_news.csv`：增量新闻队列
- `backend/app/data/scored_news.json`：已评分新闻缓存
- `backend/app/data/saved_news/`：临时抓取快照，默认忽略提交

`scored_news.json` 可以为空数组 `[]`。如果文件为空或损坏，后端会按空评分缓存处理，避免影响演示。

## 风控流程

聊天分析链路：

```text
输入事件
-> 风险识别
-> 风险分类
-> 证据抽取
-> 评分
-> 影响分析
-> 处置建议
-> 一致性复核
-> 报告生成
```

排行榜链路：

```text
新闻抓取
-> 去重入库
-> 读取本地新闻集
-> LLM/规则风险标注
-> 币种实体识别
-> 新闻榜与币种榜聚合
-> 前端展示
```

## 注意事项

- 本项目输出为风险识别和处置建议，不构成投资建议。
- Binance 新闻源可能因网络、风控或响应格式变化不可用；系统会保留本地数据降级路径。
- DeepSeek API 不可用或未配置时，部分 Agent 会使用规则兜底，结果质量会下降。
- 提交代码前检查 `.env`、`.venv`、`node_modules`、`.next` 和临时数据文件是否被忽略。
