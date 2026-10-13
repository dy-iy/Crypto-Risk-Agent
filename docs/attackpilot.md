# AttackPilot 迁入与交接

## 2026-09-12 页面与功能恢复

以 `链上交易复盘源代码/frontend/src` 为参照恢复 `LandingWarRoom`、`TaskList`、`Briefing`，替换此前精简工作台；保留原版宣传区、交易输入区、案例弹窗、任务统计/筛选及详情工作区。五类分析模块、单笔审查、批量候选、选择网络、深度分析、任务管理、知识学习、证据/日志、取证助手均使用现有 `/api/attackpilot`。公开案例入口读取真实已导入任务，不提供伪造的前端任务快照。

主题切换、原标志、Ant Design 中文语言包已恢复，所有主题选择器限定在子页面内。修复主站 Tailwind 对 Markdown 标题和列表的样式重置；窄屏把 Agent 详情/文件日志放到报告下方，避免隐藏功能。主站通用 AI 悬浮入口在本模块内交由原取证助手承担。

新报告默认要求简体中文，函数名、代码、哈希和工具协议保持原样。历史最终报告保留原文，通过 `GET /tasks/{id}/report-translation` 读取缓存、`POST` 同路径创建中文派生译文；GET 不调用模型，POST 需要登录，私有报告仍检查任务归属。缓存按任务/原文哈希/语言保存，翻译保护代码、链接、哈希和数字，失败不会用不完整结果覆盖缓存。页面默认中文，支持原文切换、失败重试；中文报告导出同时保留原文和原始证据。

报告章节提取现在保留子章节与编号证据。补丁面板只按后端 `result.verification` 显示实际执行结果，历史案例明确标为当前未验证。

已在当前会话完整翻译并导入 14 份历史记录（截图私有报告 1 份、公共历史记录 13 份），原文与代码/哈希/数字多重集合一致。9 份原文为错误终止记录，译文同样保留失败事实。模型字段标记 `assistant-translation`。公共部分打包在 `data/report-translations.zh-CN.json`，启动时幂等导入；私有截图仅存运行数据库。

验证结果：后端 58 项回归、前端 18 项回归、全量 TypeScript 和模块 ESLint 通过。离线浏览器以主站侧边栏宽度及真实 Tailwind 样式运行，检查桌面 1440px / 手机 390px 五个页面、明暗切换、中文/原文切换、实际中文缓存、登录草稿衔接、上游模块取消及下游依赖、单笔/批量检测、BNB 网络参数、任务导航、助手和 SSE 终态；无浏览器异常或未处理 API，所有写请求带共享 CSRF 头。真实模型/链上分析未在本轮调用，不能把离线通过当作线上端到端通过。

本次未运行站点开发服务、生产构建或进程管理命令；已有运行进程是否载入新代码须按现有发布流程确认。

## 当前交付

现有桌面侧边栏和移动导航新增“链上攻击复盘”。页面复用 CryptoRisk 外壳、账号弹窗与请求封装，入口 `/attackpilot`，任务库 `/attackpilot/tasks`，详情 `/attackpilot/tasks/[taskId]`，知识库 `/attackpilot/knowledge`（兼容 `/attackpilot/learning`），项目介绍 `/attackpilot/briefing`。原业务组件迁入 `frontend/components/attackpilot`，Ant Design 6 局部主题及 CSS 均限定在模块内，详情和知识页按需加载。

后端独立包为 `backend/app/attackpilot`，由现有 `backend/main.py` 注册路由和调度生命周期。原 Agent、提示词、链上取证、补丁和编译逻辑保留，并修正包导入、任务目录、模型消息、补丁验证开关及错误标记。模型固定为 `deepseek-v4-pro`。

本轮交付代码、可重复准备/导入脚本、离线测试与说明。没有启动、构建、重启或部署网站。当前运行的旧前端直接访问新路由仍为 404，需维护现有部署的人员发布这次代码后验收。

## 环境准备

部署约定：`https://crypto.kassa-wiki.top`；前端监听 3000，后端监听 8000。所有前端 API、SSE 与轮询均为相对 `/api/attackpilot/...`。

在项目根目录执行依赖准备（这些命令不启动服务）：

```bash
backend/.venv/bin/pip install -r backend/requirements.server.txt
npm ci --prefix frontend
npm ci --prefix backend/app/attackpilot --ignore-scripts
```

数据库迁移仅需 PostgreSQL 客户端的 `pg_restore`，不依赖 PostgreSQL 或 Redis 服务。当前机器已安装 `postgresql-client-14`，可解析包内备份。Node 工具依赖和原生 Linux Solidity 编译器放在忽略目录；包内旧版本 Solidity JS 别名用于兼容旧合约。

首次使用附带压缩包准备：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.attackpilot.prepare \
  --archive '2026 NCSC AttackPilot 中山大学(1).zip' \
  --credentials --compilers --export-seed --import-seed
```

- `--credentials` 用 AST 读取原配置中的链上服务配置，追加到被 Git 忽略的 `backend/.env`，权限设为 0600，不覆盖已有键，不导入原模型密钥。
- `--compilers` 提取包内 Linux Solidity 编译器至 `backend/runtime/attackpilot/compiler`。
- `--export-seed` 用 `pg_restore --file=-` 解析任务及日志表，并从 Redis AOF 补齐正文。输出可提交的脱敏 `data/demo-seed.json`。
- `--import-seed` 按原任务 ID、日志 ID 去重，写入独立 SQLite，并还原按 Agent 分组的历史日志文件。可单独重复执行此参数；不会覆盖私有任务。后端启动也会导入缺少的示例记录。

无需重新解析压缩包时：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.attackpilot.prepare --import-seed
```

配置模板见根目录 `.env.example` 及 `backend/app/attackpilot/.env.example`。实际值放入根目录 `.env` 或 `backend/.env`；沿用项目现有加载顺序：进程环境优先，根目录 `.env` 先于后端 `.env`。同名配置只保留一处，避免空值遮蔽后端配置。

| 配置 | 用途 / 默认值 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 从 `.env` 读取，用于新分析和按需翻译 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_TIMEOUT` | 复用现有模型配置 |
| `ATTACKPILOT_RPC_URLS` | JSON：Ethereum、BNBChain 的 RPC URL 数组 |
| `ATTACKPILOT_SCAN_URLS` | JSON：带 chainid、apikey 的 Etherscan v2 URL 数组 |
| `ATTACKPILOT_TENDERLY_API_KEY` / `ACCOUNT` / `PROJECT` | 后两个键的完整名称为 `ATTACKPILOT_TENDERLY_ACCOUNT`、`ATTACKPILOT_TENDERLY_PROJECT` |
| `ATTACKPILOT_MAX_TASKS` | 默认 1，最多 4 个独立任务进程 |
| `ATTACKPILOT_TASK_TIMEOUT` | 默认 3600 秒 |
| `ATTACKPILOT_RUNTIME_DIR` | 默认 `backend/runtime/attackpilot` |
| `ATTACKPILOT_DB_PATH` | 默认运行目录中的 `attackpilot.sqlite3` |
| `ATTACKPILOT_NODE_PATH` | 默认 `node` |

`GET /api/attackpilot/capabilities` 返回配置、Python 依赖、Node 工具和编译器状态。它检查本地准备状态，不代表远端凭据已经验证。单笔/批量轻量审查只需要链上 RPC；深度流程还需要模型、浏览器源码接口、Tenderly 及编译工具。原始取证阶段会使用 Tenderly，取消“补丁验证”可跳过补丁部署和回放。

## 数据、权限与结果含义

- 已整理 24 个历史任务（13 个完成、11 个失败）、615 条日志，未匹配日志为 0。旧日志中只含案例名的记录按唯一任务或唯一时间窗关联；保留原任务 ID、状态、时间与来源。历史报告不代表在当前环境重新运行成功。
- `Spectra_finance.json` 原预处理缓存内部记录为 SushiSwap，已核对内部案例名与 Hash，将其归于 SushiSwap，并去除重复缓存；不会作为 Spectra 分析依据。原无文件名缓存按内部案例名归为 ADC。Spectra 原始案例资料仍可浏览，但不会展示错误的预处理结果。
- SQLite 启用 WAL。任务、完整日志、持久化事件共用事务；最终状态不会被迟到的日志或完成消息覆盖。备份应使用 SQLite backup 功能或在暂停写入后复制数据库与 WAL。
- 访客只能浏览公共示例与公共知识。新审查、深度任务及助手需要登录；任务、日志正文、Agent 文件、交易关系、一致性报告、SSE、助手上下文和生成报告检索均检查归属。公共示例只读，公共索引重建仅管理员可用。
- 每项深度任务使用独立子进程、模型客户端与 `runtime/attackpilot/tasks/<UUID>`。队列默认逐项执行；取消或超时按任务标识终止所属进程组，包括 MCP 另建的进程组与编译工具。重启后清理中断任务的工具进程，并将原 pending/running 任务标记失败，可重新创建。
- 公共 RAG 采用原项目本地哈希向量与关键词检索。私有生成报告按当前账号实时检索，不写入共享公共索引。账号导出包含私有任务、报告、日志和事件；删除账号同步移除这些记录与任务目录。
- 登录后的取证助手对话按账号、页面范围、链和任务/交易隔离保存在浏览器；可清空历史，删除账号时同步清理。访客不持久化，切换账号或上下文后不会复用其他会话。交易输入草稿同样按账号隔离。
- “完成”表示工作流已输出报告。补丁结果单独保存在 `result.verification`：`verified`、`failed`、`skipped`、`not_run`。生成但未回放的补丁会明确标注未验证；历史结果单独标注归档来源。

## 路由与代理

接口统一以 `/api/attackpilot` 为前缀：

| 功能 | 路径 |
| --- | --- |
| 环境 / 案例 | `GET /capabilities`、`GET /dapps` |
| 审查 / 批量 / 深度 | `POST /tx-review`、`POST /tx-detect`、`POST /tx-review/deep-analysis` |
| 案例重跑 / 任务管理 | `POST /tasks`、`GET /tasks`、`GET /tasks/{id}`、`DELETE /tasks/{id}` |
| 状态操作 | `POST /tasks/{id}/cancel`、`archive`、`unarchive` |
| 日志 / SSE | `GET /tasks/{id}/logs`、`events`；`GET /task/{id}/log/{log_id}` |
| 证据 / 报告 | `GET /tasks/{id}/macro-analysis`、`automated-review`、`agent-log-files`、`agent-log-files/{file_id}` |
| 知识库 | `GET /knowledge/vulnerabilities`、`vulnerabilities/{id}`、`cases`、`cases/{id}`、`summary` |
| RAG / 助手 | `GET /rag/status`、`POST /rag/search`、`POST /rag/rebuild`、`POST /assistant/chat` |

沿用现有 session cookie、CSRF 请求头、限流与错误响应中间件。SSE 支持 `Last-Event-ID` 和 `after_id`，事件编号持久化，每 15 秒心跳；浏览器在 SSE 重连时按游标轮询补齐日志，终态关闭连接。

发布时确认现有 Nginx 的 `/` 代理至前端 3000，`/api/` 保留路径代理至后端 8001。SSE 所在 location 应禁用缓冲并允许长连接，示意配置：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

该地址只属于服务端代理配置。前端代码没有本机地址或后端端口。发布后确认域名相关 CORS、OAuth 回调和 `PUBLIC_SITE_URL` 已使用最新域名；本轮未覆盖现有运行环境的这些值。

## 可重复验证

```bash
cd backend
.venv/bin/python -m unittest evals.test_attackpilot evals.test_account_export_service evals.test_rate_limit_service evals.test_csrf_protection -v
.venv/bin/python -m unittest evals.test_attackpilot_compilers -v
```

后端回归使用临时 SQLite、模拟模型与 RPC；编译测试仅使用合成 Solidity 合约。覆盖隔离、导入、队列、取消、重启、SSE 续传、外部失败、Hash/批量边界、模块依赖、工具消息裁剪、补丁未验证标记，以及受影响的账号、CSRF、限流逻辑。

```bash
cd frontend
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/eslint components/attackpilot components/risk-dashboard.tsx components/risk-dashboard-loader.tsx lib/api.ts app/attackpilot scripts/attackpilot-smoke.mjs
```

不启动服务的浏览器验证，从项目根目录运行：

```bash
npm install --prefix /tmp/attackpilot-ui-check --no-audit --no-fund esbuild
PYTHONPATH=backend backend/.venv/bin/python -m evals.attackpilot_fixture /tmp/attackpilot-ui-check/fixtures.json
cd frontend
node scripts/attackpilot-smoke.mjs /tmp/attackpilot-ui-check
```

浏览器夹具复用真实组件与后端离线响应，拦截全部网络请求；仅 Next 路由由测试适配器替换。检查桌面 1440px、移动 390px 布局、任务详情、导航、助手展示与 CSRF；截图和结果写入 `/tmp/attackpilot-ui-check/site`。这不代替真实 Next 服务的刷新、登录和 Nginx 联调。

本轮离线结果与未完成事项见下表，真实验收不得用历史归档或模拟回答替代：

| 验证 | 状态 |
| --- | --- |
| 39 项后端与现有功能回归 | 通过 |
| 2 项工具集成测试：原生 / Node Solidity、AST、MCP 子进程 | 通过 |
| 全部 24 个历史任务的报告与日志接口 | 通过 |
| TypeScript、模块与受影响文件 ESLint | 通过 |
| 离线组件浏览器验证 | 通过，桌面/移动四个页面、助手模拟回答、公共 RAG、导航、SSE 终态与 CSRF |
| 真实 Next 路由刷新、登录返回、Nginx SSE | 本轮未启动或重新发布服务，仍待线上验收 |
| 一个历史案例重新分析 + 一笔真实交易端到端 | 本轮未调用实时模型或链上服务，仍待真实环境验收 |

真实联调时，先查看 capabilities，再登录创建历史案例任务和真实交易任务，确认排队、持续日志、断线补发、报告来源与独立验证状态；分别测试生成但不验证、验证失败/跳过，并检查另一账号无法读取这些私有任务。保留服务失败原因，不将未完成验证记为通过。
