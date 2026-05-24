# CryptoRisk Agent 技术路线

## 1. 项目定位

CryptoRisk Agent 是一个面向加密货币场景的金融风控 Multi-Agent 系统。系统以新闻、公告、项目事件、交易所异常、链上安全事件等非结构化文本为输入，自动完成风险识别、风险分类、证据抽取、风险评分、影响分析、处置建议和结构化报告生成。

项目目标不是给出投资建议，而是帮助用户快速回答三个风控问题：

- 这条信息是否构成加密货币风险事件？
- 风险严重性、信息置信度和影响范围分别是什么？
- 应该优先核实哪些事实、监控哪些信号、采取哪些风控动作？

## 2. 总体架构

系统采用前后端分离架构：

```text
用户浏览器
  -> Next.js / React / Tailwind 前端
  -> /api/... 相对路径请求
  -> Nginx 反向代理
  -> FastAPI 后端
  -> Multi-Agent 风控工作流
  -> DeepSeek API + 本地规则兜底
  -> CSV / JSON 本地数据集
```

核心技术栈：

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、Python、Pydantic
- Agent：LangChain / LangGraph 风格的多节点工作流
- 模型：DeepSeek `deepseek-v4-pro`
- 数据：`mastered_news.csv`、`raw_news.csv`、`scored_news.json`
- 部署：Nginx 将 `/api/` 代理到 FastAPI，其余路径代理到 Next.js

## 3. 前端技术路线

前端以风控工作台为核心，而不是普通展示页。主要页面包括：

- 首页总览：展示当前新闻风险、币种风险和运行状态。
- 聊天分析：用户输入事件文本，调用 `/api/chat` 获取结构化风控报告。
- 新闻风险榜：展示近 24 小时、近 7 天和全部新闻的风险排序。
- 币种风险榜：按币种聚合相关新闻，生成币种级风险视图。
- 详情页：查看单条新闻或单个币种的风险证据、摘要和关联信息。
- 系统设置页：触发新闻更新任务，并展示异步流水线进度。

前端请求策略：

- 只使用 `/api/xxx` 相对路径，避免环境绑定。
- 对排行榜请求做轻量缓存，降低页面卡顿。
- 对大列表使用前端筛选、排序和 memo 化计算，减少重复渲染。
- 新闻更新任务使用异步 job 轮询，刷新页面后仍可恢复进度显示。

## 4. 后端技术路线

后端由 FastAPI 提供统一 API，主要模块包括：

- `api/`：HTTP 路由层，负责聊天分析、排行榜、新闻更新任务。
- `agents/chat_agent/`：聊天式风控 Multi-Agent 工作流。
- `agents/ranking_agent/`：新闻批量评分与排行榜工作流。
- `services/`：数据加载、币种识别、排行榜聚合、规则评分、辅助问答。
- `prompts/`：各 Agent 的提示词模板。
- `tools/`：输入预处理、排行榜持久化等工具函数。
- `data/`：本地新闻数据和评分缓存。

后端设计原则：

- LLM 负责语义理解和复杂判断。
- 规则层负责硬约束、兜底和一致性保护。
- Pydantic / TypedDict 保持结构化数据边界。
- 本地 CSV / JSON 保证黑客松演示时可离线降级。

## 5. Chat Agent 工作流

聊天分析链路保持固定节点顺序：

```text
prepare_chat_input
  -> risk_triage_agent
  -> evidence_agent
  -> 并行分析分支
       -> score_agent
       -> classify_agent
       -> impact_agent
       -> uncertainty_agent
  -> merge_results
  -> consistency_review_agent
  -> risk_calibration_agent
  -> 并行生成分支
       -> risk_explanation_agent
       -> advice_agent
  -> report_agent
```

各节点职责：

- `prepare_chat_input`：清洗原始输入，提取实体、关键词和来源线索。
- `risk_triage_agent`：判断是否存在风险，给出初步风险状态。
- `evidence_agent`：抽取支持证据、反证、已确认事实和不确定点。
- `score_agent`：只基于原始文本和结构化 evidence 评分，避免被其他 Agent 的自然语言判断污染。
- `classify_agent`：输出主风险类别和次级类别。
- `impact_agent`：分析潜在影响对象、资产、协议和市场传导。
- `uncertainty_agent`：识别未确认信息、缺失证据和过度推断风险。
- `consistency_review_agent`：只检查结构化矛盾，不自由重评分，不覆盖原始评分。
- `risk_calibration_agent`：执行硬规则校准，区分风险严重性和信息置信度。
- `risk_explanation_agent`：生成用户可读的简要解释。
- `advice_agent`：生成风控建议，不输出投资指令。
- `report_agent`：汇总最终结构化报告。

## 6. 评分与置信度设计

系统将两个维度拆开：

- `risk_score`：事件风险严重性，表示事件本身的危害程度。
- `confidence_score`：信息可信度，表示当前证据和来源的可靠程度。

关键原则：

- 不确定性只能降低 `confidence_score`，不能直接降低 `risk_score`。
- “官方尚未确认”“信息来源有限”“仍在发展中”不能把高危攻击事件降为中风险。
- 如果原文已经明确包含已发生攻击、大额资产异常、资金外流、跨链、兑换、Tornado Cash 或 mixer 等清洗信号，则触发高危硬规则。
- 对未授权铸造、伪造资产、异常增发等事件，系统按名义价值或可变现风险敞口评估严重性。

示例硬规则：

```text
已发生攻击
+ 大额资产异常
+ 资金外流 / 跨链 / 兑换 / Tornado Cash / mixer
=> risk_score 不得低于 85
```

这样可以避免 Multi-Agent 链路中前置 Agent 的保守表述把后续评分拉低。

## 7. 排行榜技术路线

排行榜系统面向批量新闻处理，数据链路如下：

```text
Binance Square 新闻源
  -> 抓取近 7 天新闻
  -> 去重写入 raw_news.csv / mastered_news.csv
  -> 增量 Agent 标注
  -> 写入 scored_news.json
  -> 新闻风险榜聚合
  -> 币种实体抽取
  -> 币种风险榜聚合
  -> 前端展示
```

新闻更新使用异步 job：

- 点击“更新新闻”后立即创建任务。
- 后端持续更新 crawler、dedupe、agent、ranking 四个阶段进度。
- 前端轮询 job 状态。
- 刷新页面后可恢复当前 job 进度。
- 如果新闻源或 LLM 异常，系统保留本地缓存结果，避免演示中断。

批量标注优化：

- `RANKING_AGENT_CONCURRENCY` 控制排行榜 Agent 并发数。
- 已评分新闻不重复写入，减少 I/O 和页面卡顿。
- 数据加载层对 `scored_news.json` 做缓存，文件变化后自动刷新。

## 8. 数据与存储设计

项目采用轻量本地存储，适合黑客松快速演示：

- `mastered_news.csv`：主新闻集，保存已入库新闻。
- `raw_news.csv`：增量抓取队列。
- `scored_news.json`：新闻评分结果缓存。
- `saved_news/`：临时抓取快照。

数据设计特点：

- CSV 便于人工检查和修正。
- JSON 便于前端快速读取结构化评分。
- 空文件或损坏 JSON 会降级为空数据，避免服务崩溃。
- 后续可平滑替换为 PostgreSQL、Redis 或向量数据库。

## 9. Prompt 与规则协同

项目不是单纯依赖一个大 prompt，而是采用“Prompt + 结构化状态 + 规则校准”的组合：

- Prompt 负责语义理解、证据归纳和解释生成。
- 结构化字段负责跨 Agent 传递事实和评分。
- 规则校准负责处理高危事件下限、提现暂停、未授权铸造等确定性场景。
- 一致性审查只发现矛盾，不擅自覆盖评分。

这种设计的好处：

- 可解释性更强。
- 避免单个 Agent 幻觉影响最终结果。
- 关键风控红线可控。
- 便于后续接入更多数据源和规则。

## 10. 部署路线

线上访问入口：

```text
https://kassa-wiki.top
```

Nginx 路由：

```text
/      -> Next.js 前端
/api/  -> FastAPI 后端
```

部署约束：

- 前端代码只请求 `/api/xxx`。
- 不在前端硬编码本地地址或端口。
- DeepSeek API Key 只放在后端 `.env`。
- `.env`、`.venv`、`node_modules`、`.next`、临时数据文件不提交。

## 11. 可扩展方向

后续可以沿三条路线继续增强：

1. 数据源扩展
   - 接入链上浏览器、交易所公告、安全公司通报、X/Twitter、Telegram、GitHub 安全公告。
   - 增加链上地址、交易哈希、合约地址的结构化解析。

2. 风控能力扩展
   - 引入资产价格、流动性、TVL、交易所充提状态等实时指标。
   - 增加项目方、交易所、链、协议、稳定币等实体画像。
   - 建立事件相似度检索和历史案例对比。

3. 工程能力扩展
   - 用数据库替代本地 CSV / JSON。
   - 用消息队列处理批量新闻更新。
   - 增加任务重试、审计日志和模型输出版本管理。
   - 引入评测集，持续校准评分规则和 prompt。

## 12. 黑客松展示亮点

- 面向真实加密货币风控场景，而不是通用聊天机器人。
- 支持聊天分析和新闻/币种排行榜两种使用方式。
- Multi-Agent 分工明确，输出结构化可解释报告。
- 区分风险严重性和信息置信度，减少“信息未完全确认导致风险被低估”的问题。
- 对未授权铸造、资金外流、跨链和混币等 Web3 高危信号有硬规则保护。
- 支持异步新闻更新和页面进度恢复，适合现场演示。
- DeepSeek 不可用时具备规则兜底和本地数据降级能力。
