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
- **【新增】链上攻击复盘（AttackPilot）**：从交易哈希出发，完成交易取证、根因定位、补丁生成和执行验证，详见下方独立介绍。
- 产品化运行诊断：提供请求追踪、安全响应头、输入长度边界和系统 readiness 检查。

## 【新增内容】链上攻击复盘（AttackPilot）

**AttackPilot 是本次新增加的链上安全分析模块**，在原有新闻、事件与资产风险研判能力之上，增加面向 Ethereum、BNB Chain 攻击交易的深度复盘工作台。用户可提交交易哈希或载入公共历史案例，由多个 Agent 协作整理攻击过程、定位漏洞、生成源码补丁，并通过原版与补丁版执行对照检查修复效果。

### 新增能力与使用入口

- **交易审查与深度调查**：侧边栏进入 `/attackpilot`，支持单笔、批量交易审查；深度任务可对输入集合内的多笔交易排序、识别辅助步骤与漏洞触发候选，并保留跨交易调查上下文。
- **攻击过程可视化与报告交付**：集中展示调用轨迹、资金流、攻击时间线、根因、实际补丁和验证状态；逐笔对比交易发起地址的 ETH/BNB 余额净变化（含 Gas），支持导出 Markdown 报告与 JSON 证据包。
- **案例学习与任务管理**：通过 `/attackpilot/tasks` 查看任务与实时 Agent 日志，通过 `/attackpilot/knowledge` 检索漏洞和历史案例；公共案例可浏览，登录后可创建和管理自己的私有分析任务。

典型流程：**提交交易 → 链上取证 → 多 Agent 调查与根因定位 → 生成补丁 → 原版/补丁版回放 → 输出带证据的复盘报告**。

### 技术优势

| 技术优势 | 实现方式 | 实际价值 |
| --- | --- | --- |
| **多 Agent 分工与共享记忆** | 交易分析、轨迹调查、任务协调、补丁生成和判定由专职 Agent 协作，共享调查上下文，并通过 MCP 调用取证与编译工具。 | 将调查、修复、验证串成同一工作流，减少人工切换工具和重复整理多笔交易信息。 |
| **真实历史证据交叉核验** | 将 RPC 原始交易及回执与 Tenderly 历史回放核对，检查网络、交易位置、执行状态、Gas 和事件。 | 在分析与补丁验证前确认历史基准，便于发现取证缺失和回放偏差。 |
| **源码、字节码与补丁绑定** | 利用编译器 AST、源码映射和实际调用定位修复目标，校验历史运行时代码、存储布局及 immutable，并记录实际应用的源码差异。 | 将根因、修改位置和被执行的代码对应起来，让补丁验证有明确的代码依据。 |
| **原版/补丁版连续状态回放** | 从相同历史起点分别执行原版与补丁版攻击交易序列，后续步骤承接前一步状态，补丁侧替换目标运行时代码，并检查声明的资金、权限或状态安全条件。 | 观察修复对多步骤攻击路径及其结果的实际影响，形成可核对的执行对照。 |
| **执行证据决定验证结论** | 对原始请求与响应、交易顺序、补丁完整性、修改代码覆盖和声明安全条件进行机器校验；保留证据摘要与引用，支持离线复核。 | 验证结论可追溯到实际执行记录；缺失、冲突或失败证据会明确显示为未确认或阻断。 |
| **本地 RAG 知识复用** | 结合本地哈希向量与关键词检索，召回相似漏洞、历史案例和当前用户的已有复盘报告，私有报告按账号隔离。 | 为调查和修复提供可引用的历史上下文，无需额外部署向量数据库。 |
| **历史估值依据可追溯** | 为配置覆盖的资产读取 Chainlink 历史参考价，保留 Feed、轮次、精度和报价时间，缺失或过期时记录原因。 | 资金变化估值可回查当时的价格依据，报告区分历史参考价与协议实际读取的预言机证据。 |

验证结论覆盖本次提交并实际回放的攻击交易及声明的安全条件。完整分析需配置链上 RPC、区块浏览器源码接口、模型、Tenderly 和对应 Solidity 编译器；配置、部署与能力边界见 [AttackPilot 模块文档](docs/attackpilot.md)。

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

后端读取 `.env` 或环境变量；可从仓库根目录的 `.env.example` 复制为 `.env` 后替换占位值。

```env
DEEPSEEK_API_KEY=你的 DeepSeek API Key
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=30

AUTH_PASSWORD_PEPPER=建议设置一段随机强密钥
CORS_ALLOWED_ORIGINS=https://kassa-wiki.top,https://www.kassa-wiki.top
ALLOW_LOCAL_CORS=0
ALLOW_USER_ID_QUERY_OVERRIDE=0
ALLOW_PUBLIC_SYSTEM_OBSERVABILITY=0
ALLOW_SYSTEM_EVENT_GLOBAL_QUERY=0
SYSTEM_ADMIN_USERNAMES=
SYSTEM_ADMIN_USER_IDS=user-替换为管理员账号ID
ALLOW_ADMIN_USERNAME_REGISTRATION=0
DAILY_SCHEDULER_ENABLED=1
CSRF_PROTECTION_ENABLED=1
API_RATE_LIMIT_ENABLED=1
AUTH_RATE_LIMIT_PER_MINUTE=8
AGENT_RATE_LIMIT_PER_5_MINUTES=30
MUTATION_RATE_LIMIT_PER_MINUTE=90
MAX_REQUEST_BODY_BYTES=1000000
TRUST_PROXY_HEADERS=1
TASK_AUDIT_RETENTION_DAYS=30
TASK_AUDIT_MAX_EVENTS=20000
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
- `backend/app/data/portfolio.sqlite3`
- `backend/app/data/daily_reports/`
- `backend/app/data/sim_accounts.json`
- `backend/app/data/portfolio_state.json`
- `backend/app/data/portfolio_refresh_jobs.json`
- `backend/app/data/task_audit.sqlite3`
- `backend/app/data/update_jobs.json`
- `backend/app/data/*.invalid.*.bak`
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
- `POST /api/auth/change-password`：登录用户修改密码，成功后撤销其他登录会话。
- `GET /api/auth/sessions`：登录用户查看自己的活跃会话元数据。
- `POST /api/auth/sessions/revoke-others`：登录用户撤销除当前会话外的其他登录会话。
- `GET /api/account/security-events`：登录用户查看自己的账号安全事件。
- `GET /api/account/export`：登录用户导出自己的分析报告、收藏、资产 watchlist、完整日报、模拟交易账户状态、登录会话元数据和账号安全事件。
- `DELETE /api/account?confirm=delete-my-account`：登录用户用当前密码二次确认后，删除自己的账号、会话、收藏、分析报告、资产 watchlist、日报和模拟交易账户状态。
- `GET /api/daily-report`：获取个人风险日报。
- `POST /api/daily-report/generate`：生成个人风险日报。
- `GET /api/sim/state`：获取模拟交易状态。
- `GET /api/system/readiness`：检查生产环境关键配置、数据文件、运行目录、安全开关、SQLite 和运行态 JSON 可写性及 JSON 合法性。
- `GET /api/system/version`：获取服务版本、启动时间和运行时长。
- `GET /api/system/task-events`：管理员查询新闻更新、组合刷新、Chat 分析、风险助手等审计事件。
- `GET /api/system/audit-summary`：管理员查看最近窗口内各类任务和分析的成功、失败、错误率和最近事件。
- `POST /api/system/task-events/prune`：管理员按保留天数和最大事件数清理审计账本。
- `POST /api/system/sim-accounts/prune`：管理员清理过期游客模拟交易账户，不影响登录用户模拟账户。
- `POST /api/system/auth-sessions/prune`：管理员清理已过期登录会话，降低账号库长期运行的无效会话残留。
- `POST /api/system/runtime-jobs/prune`：管理员清理新闻更新与组合刷新运行态任务状态，保留排队/运行中的任务。
- `POST /api/system/invalid-json-backups/prune`：管理员清理过期损坏 JSON 隔离备份，保留近期备份用于排障。
- `GET /api/system/rate-limits`：管理员查看当前 API 限流规则和运行中桶状态。
- `GET /api/system/storage-inventory`：管理员查看 SQLite、日报文件和模拟交易运行态的数据量与文件大小。
- `GET /api/system/backup-manifest`：管理员查看生产备份清单，确认 SQLite、WAL/SHM、日报目录和运行态 JSON 的备份范围。
- `GET /api/system/daily-scheduler`：管理员查看每日 08:00 新闻更新与资产日报定时任务状态。
- `PATCH /api/system/daily-scheduler`：管理员启动或暂停每日定时任务。
- `POST /api/system/daily-scheduler/run-now`：管理员手动执行一次新闻更新与订阅用户资产日报生成。

## 产品化上线门禁

部署到公网前建议检查：

- 访问 `GET /api/system/readiness`，状态应为 `ready` 或确认可接受的 `degraded`。
- `AUTH_PASSWORD_PEPPER` 必须设置，`ALLOW_USER_ID_QUERY_OVERRIDE` 必须保持 `0`。
- `CSRF_PROTECTION_ENABLED` 必须保持 `1`，Cookie 登录态的写请求会要求 `X-CryptoRisk-CSRF: 1`。
- `ALLOW_PUBLIC_SYSTEM_OBSERVABILITY` 必须保持 `0`；即使临时开启公开只读观测，任务事件明细、存储盘点和审计清理也始终只允许管理员访问。
- `ALLOW_PUBLIC_REPORT_DEBUG` 必须保持 `0`；公网 API 默认只返回证据链、评分路径等解释字段，不公开内部 `debug`、原始 Agent 状态或诊断对象。
- 推荐先注册普通账号，再通过 `SYSTEM_ADMIN_USER_IDS=user-...` 配置系统观测管理员；`SYSTEM_ADMIN_USERNAMES` 适合内部受控环境。
- `ALLOW_ADMIN_USERNAME_REGISTRATION` 必须保持 `0`，避免公网用户抢注 `SYSTEM_ADMIN_USERNAMES` 中的管理员用户名。
- `ALLOW_SYSTEM_EVENT_GLOBAL_QUERY` 是旧兼容开关，系统观测已改为管理员可见，生产环境不建议开启。
- 生产环境建议关闭 `ALLOW_LOCAL_CORS` 和 `CRYPTO_RISK_AGENT_OFFLINE`。
- `DAILY_SCHEDULER_ENABLED=1` 时后端会启动每日 08:00 定时任务；可在系统设置页由管理员暂停或恢复。
- `DEEPSEEK_API_KEY` 缺失时系统仍可规则兜底，但 Agent 深度会下降。
- `DEEPSEEK_CLIENT` readiness 会检查 Python `openai` 客户端是否可导入；有 API Key 但客户端缺失时应先安装后端依赖。
- `DEEPSEEK_MODEL` 必须保持 `deepseek-v4-pro`；`DEEPSEEK_TIMEOUT` 应为 1-120 秒数字，readiness 会提示模型漂移或非法 timeout。
- Readiness 会检查 `auth.sqlite3`、`analysis_reports.sqlite3`、`portfolio.sqlite3`、`task_audit.sqlite3`、`sim_accounts.json`、`portfolio_refresh_jobs.json` 和 `update_jobs.json`；未创建的可选运行时文件不会阻塞启动，但已存在且不可写或不是合法 JSON 会降级。运行态 JSON 加载时会把损坏文件隔离为 `.invalid.*.bak` 后以空状态继续，避免服务被坏文件拖垮。
- 所有 API 响应会带 `X-Request-ID` 和 `X-Process-Time-Ms`，便于线上日志定位。
- 登录/注册、Agent 分析和写操作默认开启内存限流；被限流时返回 `429`、`Retry-After` 和 `X-RateLimit-*` 响应头。
- 聊天分析输入限制为 12000 字符，风险助手问题限制为 2000 字符，选中文本限制为 12000 字符；全局请求体默认限制为 `MAX_REQUEST_BODY_BYTES=1000000`，超限返回 `413`。
- 新闻更新、组合刷新、Chat 分析和风险助手会写入任务审计账本，可通过 `/api/system/task-events?job_kind=news_update`、`/api/system/task-events?job_kind=portfolio_refresh`、`/api/system/task-events?job_kind=chat_analysis` 或 `/api/system/task-events?job_kind=risk_assistant` 查询。
- 分析审计只保存输入长度、短哈希、风险摘要和耗时，不保存用户提交原文。
- 账号注册、登录、改密、会话撤销、退出登录及失败登录/改密会写入账号安全审计；安全事件包含客户端摘要和 IP 短哈希，失败登录只保存用户名短哈希，不保存明文用户名或密码。
- 登录用户可在设置页修改密码、查看/撤销其他登录会话、查看账号安全事件、导出或删除自己的账号数据；会话列表显示客户端摘要和 IP 短哈希，不展示完整 IP；修改密码会撤销其他登录会话，导出包含完整日报 payload、模拟交易账户快照、登录会话元数据和账号安全事件，删除账号需要输入当前密码并确认 DELETE，会清除当前用户模拟仓位和用户关联审计事件，只保留一条匿名删除动作审计。
- 审计汇总可由管理员通过 `/api/system/audit-summary?window_hours=24` 查看；临时开启公开只读观测时，审计汇总会隐藏最近事件详情；审计保留策略由 `TASK_AUDIT_RETENTION_DAYS` 和 `TASK_AUDIT_MAX_EVENTS` 控制，可通过 `/api/system/task-events/prune` 主动清理；过期游客模拟账户可通过 `/api/system/sim-accounts/prune?retention_days=14` 清理；已过期登录会话可通过 `/api/system/auth-sessions/prune` 清理；新闻更新和组合刷新任务状态可通过 `/api/system/runtime-jobs/prune?retention_days=14&max_jobs=100` 清理，排队/运行中的任务会保留；损坏 JSON 隔离备份可通过 `/api/system/invalid-json-backups/prune?retention_days=30` 清理，近期备份会保留用于排障；管理员清理动作会写入 `system_admin` 审计事件，记录操作者和清理计数。
- 存储盘点可由管理员通过 `/api/system/storage-inventory` 查看，用于确认生产数据是否落在持久化目录和评估备份规模；备份清单可通过 `/api/system/backup-manifest` 查看，用于核对 SQLite、WAL/SHM、日报目录、模拟交易账户状态和运行态 JSON 是否纳入持久化备份；这两个接口不受公开观测开关影响，始终要求管理员账号。
- 设置页会公开显示 readiness；审计汇总、最近审计明细和限流状态需要管理员账号，若黑客松演示必须公开展示只读观测，可临时设置 `ALLOW_PUBLIC_SYSTEM_OBSERVABILITY=1`；任务事件明细、存储盘点、审计清理、游客模拟账户清理、过期登录会话清理和运行态任务状态清理始终要求管理员账号。
- 自选资产/持仓 watchlist 使用 `backend/app/data/portfolio.sqlite3` 持久化；模拟交易账户状态使用 `backend/app/data/sim_accounts.json` 持久化，服务重启后会自动恢复；旧 `portfolio_state.json` 中的 watchlist 会在首次访问时自动迁移一次。

## 本地检查

本项目收尾时不要执行服务启动、前端开发服务、前端构建或 PM2 命令。允许使用以下静态检查和回归测试：

```bash
PYTHONPATH=backend python3 backend/evals/run_product_gate.py --pretty
PYTHONPATH=backend python3 -m unittest backend.evals.test_quality_gate backend.evals.test_account_export_service backend.evals.test_csrf_protection backend.evals.test_auth_service_admin_registration backend.evals.test_system_observability_access backend.evals.test_rate_limit_service backend.evals.test_product_readiness_service backend.evals.test_runtime_job_pruning
python3 -m compileall backend/app backend/evals
```

```bash
cd frontend
npm run lint
npx tsc --noEmit
```

风控指标门禁可在需要完整评测时运行：

```bash
PYTHONPATH=backend python3 backend/evals/run_risk_eval.py --output-json /tmp/cryptorisk-risk-eval.json
PYTHONPATH=backend python3 backend/evals/run_product_gate.py --risk-eval-json /tmp/cryptorisk-risk-eval.json --pretty
```

## 部署备注

- 线上入口统一使用 `https://kassa-wiki.top`。
- 前端请求必须保持 `/api/...` 相对路径。
- 后端默认 CORS 只允许公网域名；如需本地浏览器直连调试，显式设置 `ALLOW_LOCAL_CORS=1`。
- Nginx 反代部署默认信任 `X-Forwarded-For` 做限流身份；如果后端会被公网直接访问，应设置 `TRUST_PROXY_HEADERS=0`。
- 用户身份依赖 `cryptorisk_session` HttpOnly Cookie。
- `ALLOW_USER_ID_QUERY_OVERRIDE` 默认关闭，避免通过查询参数访问或修改其他用户的资产数据。

## Skill

仓库内置 `skills/crypto-risk-agent/`，可供支持 Skill 的 Agent 客户端读取项目 API 契约和调用脚本。脚本默认面向公开站点 `/api` 契约，适合快速演示风控能力。
