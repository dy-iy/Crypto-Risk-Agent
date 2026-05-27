# Chat Agent 框架、工作流程与 Agent 设计说明

这份文档用于向导师汇报项目中的 `chat_agent`。重点不是泛泛介绍 Multi-Agent，而是结合当前代码说明：用户输入如何进入系统、每个 Agent 做什么、prompt 如何约束模型、结构化状态如何流转，以及为什么要加入规则校准。

## 1. 一句话介绍

`chat_agent` 是一个面向加密货币金融风控的聊天式 Multi-Agent 工作流。

用户在前端输入一段加密货币新闻、公告、链上安全事件、交易所异常或项目事件后，后端会把它交给多个专职 Agent 分工处理，最终输出一份结构化风险报告，包括：

- 风险状态
- 风险类别
- 风险评分
- 证据与反证
- 影响范围
- 不确定性
- 风控建议

对应入口代码：

- FastAPI 接口：`backend/main.py`
- 工作流入口：`backend/app/agents/chat_agent/graph.py`
- 状态结构：`backend/app/state.py`
- 输出 schema：`backend/app/schemas.py`

## 2. 从接口到 Agent 的调用链

前端聊天窗口只需要请求后端 `/api/chat`。

代码位置：`backend/main.py`

```python
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    final_report = run_chat_agent(request.message)
    return ChatResponse(data=RiskReport.model_validate(final_report))
```

这里的核心是 `run_chat_agent(request.message)`。

代码位置：`backend/app/agents/chat_agent/graph.py`

```python
def run_chat_agent(user_message: str) -> dict:
    initial_state: CryptoRiskState = {
        "original_text": user_message,
        "raw_agent_outputs": {},
    }
    result = chat_workflow.invoke(initial_state)
    return result.get("final_report", {})
```

也就是说，用户输入会被放进一个共享状态 `CryptoRiskState`，然后由工作流逐步处理。

## 3. 共享状态 CryptoRiskState

所有 Agent 不是靠自然语言互相传递结果，而是共享一个结构化状态对象。

代码位置：`backend/app/state.py`

核心字段可以分为几类：

| 类型 | 典型字段 | 作用 |
|---|---|---|
| 原始输入 | `original_text`, `raw_text`, `cleaned_text` | 保存用户输入和清洗后的文本 |
| 输入解析 | `input_type`, `entities`, `keyword_refs`, `source_hint` | 识别事件类型、币种、交易所、地址、关键词和来源 |
| 风险分诊 | `has_risk`, `risk_status`, `risk_signals`, `non_risk_factors` | 判断是否有风险以及风险状态 |
| 证据 | `supporting_evidence`, `counter_evidence`, `confirmed_facts`, `missing_info`, `evidence_quality` | 保存支持证据、反证、已确认事实和缺失信息 |
| 分类 | `primary_category`, `secondary_categories`, `risk_categories` | 输出风险类别 |
| 评分 | `risk_score`, `final_risk_score`, `severity_score`, `confidence_score`, `urgency_score`, `contagion_score`, `risk_level` | 多维度评分 |
| 影响 | `impact`, `affected_entities`, `affected_assets`, `loss_estimate`, `systemic_risk`, `user_asset_risk` | 分析影响对象和影响范围 |
| 不确定性 | `verified_claims`, `unverified_claims`, `missing_information`, `overclaiming_risks` | 防止过度推断 |
| 建议与报告 | `risk_explanation`, `advice`, `final_report` | 面向前端展示 |
| 调试记录 | `raw_agent_outputs` | 保存每个 Agent 的原始输出，便于展示和排查 |

汇报时可以说：这个设计让每个 Agent 的输入输出都有边界，方便调试，也方便前端直接展示。

## 4. 总体工作流

代码位置：`backend/app/agents/chat_agent/graph.py`

当前工作流是：

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

对应代码：

```python
class EvidenceGroundedChatWorkflow:
    def invoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        state = prepare_chat_input(initial_state)
        state = risk_triage_agent(state)
        state = evidence_agent(state)

        state = _run_parallel(
            state,
            {
                "score_agent": score_agent,
                "classify_agent": classify_agent,
                "impact_agent": impact_agent,
                "uncertainty_agent": uncertainty_agent,
            },
            ANALYSIS_BRANCH_FIELDS,
        )

        state = merge_results(state)
        state = consistency_review_agent(state)
        state = risk_calibration_agent(state)

        state = _run_parallel(
            state,
            {
                "risk_explanation_agent": risk_explanation_agent,
                "advice_agent": advice_agent,
            },
            GENERATION_BRANCH_FIELDS,
        )
        return report_agent(state)
```

这里有两个特点：

1. 先做证据抽取，再做评分、分类、影响和不确定性分析。
2. 评分、分类、影响、不确定性可以并行执行，因为它们都基于同一份原文和证据。

并行执行由 `_run_parallel()` 完成，内部使用 `ThreadPoolExecutor`。每个分支拿到状态副本，执行完后只把允许的字段合并回主状态，避免分支之间互相污染。

## 5. 输入预处理 prepare_chat_input

代码位置：`backend/app/tools/chat_tools.py`

这个节点不是 LLM，而是规则工具。它负责把用户输入变成后续 Agent 更好处理的结构化信息。

主要逻辑：

- 清洗文本：`cleaned_text = " ".join(original_text.split())`
- 识别钱包地址：例如 `0x...`、Tron 地址、Bitcoin 地址
- 识别币种 ticker：例如 `BTC`, `ETH`, `USDT`
- 识别交易所：例如 Binance、OKX、Coinbase、Bybit
- 识别公链：例如 Ethereum、BSC、Solana、Bitcoin
- 根据关键词粗略判断输入类型
- 抽取关键词上下文，例如“攻击”“被盗”“暂停提现”“脱锚”“大额转账”
- 抽取来源提示，例如“据某媒体报道”“官方公告”

输出写入状态字段：

```text
cleaned_text
input_type
entities
keyword_refs
source_hint
parsed_input
raw_agent_outputs["input_tool"]
```

汇报时可以说：这一步相当于给 LLM 做输入结构化，减少模型盲猜。

## 6. 公共 Prompt 规则

所有关键 Agent 都会引入同一段公共规则。

代码位置：`backend/app/prompts/common.py`

核心内容：

```python
COMMON_AGENT_RULES = """
共同原则：
1. 你必须阅读 raw_text 原文，不得只依赖前一个 agent 的结论。
2. 前序 agent 的输出只能作为上下文参考，不是绝对事实。
3. keyword_refs 只是关键词和实体提示，不能作为风险判断的直接依据。
4. 如果原文证据不足，你必须明确说明“不足以确认”，不能补充原文没有的信息。
5. 输出必须是可解析 JSON，不要添加 Markdown 代码块。
""".strip()
```

这段规则解决了 Multi-Agent 中常见的问题：

- 后面的 Agent 不能盲目相信前一个 Agent。
- 关键词只能提示，不能直接定罪。
- 证据不足时必须承认不足。
- 所有输出必须是 JSON，方便代码解析。

## 7. Risk Triage Agent：第一层风险分诊

代码位置：

- `backend/app/agents/chat_agent/risk_triage_agent.py`
- `backend/app/prompts/triage_prompt.py`

职责：

`risk_triage_agent` 是第一层风控分流，只判断风险状态，不评分。

它会输出：

```json
{
  "risk_status": "potential_risk",
  "risk_summary": "风险定性摘要",
  "risk_signals": ["原文支持风险状态的信号"],
  "non_risk_factors": ["降低风险级别或说明未确认的因素"],
  "confidence": "high|medium|low"
}
```

Prompt 中明确规定 `risk_status` 只能是：

```text
no_risk
potential_risk
confirmed_risk
resolved_risk
uncertain
systemic_risk
```

这里的关键设计是：

- 分诊 Agent 不打分，只定性。
- 如果是交易所暂停提现、用户大量无法提款，即使官方解释为钱包维护，也应视为已发生的运营或流动性风险。
- “尚未确认攻击或资金损失”只能降低攻击类结论，不能否定已经发生的提现异常。

状态写入字段：

```text
has_risk
risk_status
risk_summary
risk_signals
non_risk_factors
triage_confidence
raw_agent_outputs["risk_triage_agent"]
```

汇报时可以这样讲：第一层先判断“有没有风险、风险是否已经发生”，但不直接给分，避免早期判断影响评分细节。

## 8. Evidence Agent：证据抽取

代码位置：

- `backend/app/agents/chat_agent/evidence_agent.py`
- `backend/app/prompts/evidence_prompt.py`

职责：

`evidence_agent` 是整个工作流的核心，因为后续评分、分类、影响分析都要基于证据。

它的 prompt 要求模型区分：

- 原文事实
- 官方说法
- 社群反馈
- 模型推测

要求输出：

```json
{
  "confirmed_facts": ["原文中已经明确发生或声明的事实"],
  "risk_signals": ["直接风险信号"],
  "uncertainty_points": ["仍需验证或原文没有给出的信息"],
  "evidence_items": [
    {
      "text": "证据原文片段",
      "source_type": "原文事实|官方说法|社群反馈|模型推测",
      "signal_type": "withdrawal_pause|confirmed_attack|actual_loss|market_impact|other",
      "supports": "支持的风险状态或结论"
    }
  ],
  "supporting_evidence": [],
  "counter_evidence": [],
  "missing_info": [],
  "evidence_quality": "strong|medium|weak|none"
}
```

代码里还有两个校准函数：

- `_calibrate_exchange_withdrawal_evidence`
- `_calibrate_confirmed_attack_evidence`

它们用于补强高危场景，例如：

- 暂停提现
- 大量用户无法提款
- 已确认攻击
- 实际损失
- 资金转移或清洗路径

状态写入字段：

```text
supporting_evidence
counter_evidence
missing_info
confirmed_facts
risk_signals
uncertainty_points
evidence_items
evidence_quality
evidence
raw_agent_outputs["evidence_agent"]
```

汇报时可以说：我们不是让模型直接下结论，而是先要求它把证据、反证和缺失信息分开列出，这样后续评分更可解释。

## 9. 并行分析分支

证据抽取完成后，工作流进入并行分析分支。

代码位置：`backend/app/agents/chat_agent/graph.py`

```python
state = _run_parallel(
    state,
    {
        "score_agent": score_agent,
        "classify_agent": classify_agent,
        "impact_agent": impact_agent,
        "uncertainty_agent": uncertainty_agent,
    },
    ANALYSIS_BRANCH_FIELDS,
)
```

这四个 Agent 可以并行，因为它们都依赖同一份原文和证据，但彼此不应该互相影响。

### 9.1 Score Agent：风险评分

代码位置：

- `backend/app/agents/chat_agent/score_agent.py`
- `backend/app/prompts/score_prompt.py`

职责：

输出风险分数、风险等级和多维度评分。

重要 prompt 约束：

```text
你只能基于 raw_text 和 evidence_result 评分。
不得读取或继承 triage、classify、impact、uncertainty、review、calibration 等其他 Agent 的自然语言总结或风险判断。
不要把“证据置信度不足”等同于“事件严重性低”；证据不足主要降低 confidence_score。
```

这是一个关键设计点：风险严重性和信息置信度分开。

输出字段：

```json
{
  "severity_score": 20,
  "confidence_score": 45,
  "urgency_score": 15,
  "contagion_score": 20,
  "final_risk_score": 28,
  "risk_score": 28,
  "risk_level": "低风险|轻微风险|中风险|高风险|极高风险",
  "score_reason": "评分理由",
  "score_factors": {},
  "score_breakdown": {},
  "confidence": "high|medium|low"
}
```

评分维度：

| 字段 | 含义 |
|---|---|
| `severity_score` | 事件严重性 |
| `confidence_score` | 当前信息可信度 |
| `urgency_score` | 处置紧急程度 |
| `contagion_score` | 传导或扩散风险 |
| `risk_score/final_risk_score` | 最终风险严重性分数 |

代码中还会做 fallback 和硬规则下限，例如：

- 已确认攻击
- 实际资金损失
- 大额损失
- 未授权铸造或伪造资产
- 跨链、兑换、Tornado Cash、mixer 等转移或清洗信号
- 交易所暂停提现

汇报时可以说：评分 Agent 不直接继承其他 Agent 的判断，避免“前序错误一路传递”。它只看原文和证据。

### 9.2 Classify Agent：风险分类

代码位置：

- `backend/app/agents/chat_agent/classify_agent.py`
- `backend/app/prompts/classify_prompt.py`

职责：

把事件归入固定风险类别。

固定类别包括：

```text
链上漏洞 / 攻击风险
诈骗 / 跑路 / Rug Pull 风险
监管与法律风险
交易所与系统运维风险
稳定币异常风险
爆仓 / 清算风险
大额转账 / 巨鲸行为风险
异常行情波动风险
项目治理 / 团队异常风险
偿付能力 / 储备 / 流动性风险
基础设施 / 协议层异常风险
宏观 / 政策冲击风险
```

Prompt 约束：

```text
只能从固定风险类别中选择，不允许创造新类别。
必须基于 raw_text 和 evidence_result 分类，而不是只看 keyword_refs。
不允许默认塞“异常行情波动风险”。
```

输出字段：

```text
primary_category
secondary_categories
classification_reason
classification_confidence
risk_categories
```

代码中也有规则校准：

- 如果检测到交易所暂停提现，主类校准为“交易所与系统运维风险”，次类补充“偿付能力 / 储备 / 流动性风险”。
- 如果检测到已确认攻击且有损失，主类校准为“链上漏洞 / 攻击风险”。
- 如果涉及 RPC、验证网络、跨链、预言机等路径，补充“基础设施 / 协议层异常风险”。

### 9.3 Impact Agent：影响分析

代码位置：

- `backend/app/agents/chat_agent/impact_agent.py`
- `backend/app/prompts/impact_prompt.py`

职责：

分析影响对象、影响资产、损失估计、系统性风险和用户资产风险。

Prompt 约束：

```text
不要模板硬套；没有依据时不能写用户资产损失、大规模抛售、交易所风险等过度推断。
影响描述要与 evidence_result、risk_score 保持一致。
必须区分“单一项目/特定配置影响”和“系统性扩散影响”。
```

输出字段：

```json
{
  "affected_entities": ["受影响项目、交易所、协议或用户群体"],
  "affected_assets": ["受影响资产或代币"],
  "loss_estimate": "原文给出的损失估计；没有则为空字符串",
  "impact": [
    {
      "target": "影响对象",
      "description": "基于原文证据的影响说明"
    }
  ],
  "impact_scope": "none|short_term|long_term|protocol|market|systemic",
  "impact_severity": "none|low|medium|high",
  "systemic_risk": "none|low|medium|high",
  "user_asset_risk": "none|low|medium|high"
}
```

汇报时可以说：影响分析 Agent 负责回答“这个事件影响谁、影响什么资产、会不会扩散”，但是它不能编造没有证据的市场恐慌或资金损失。

### 9.4 Uncertainty Agent：不确定性识别

代码位置：

- `backend/app/agents/chat_agent/uncertainty_agent.py`
- `backend/app/prompts/uncertainty_prompt.py`

职责：

识别哪些结论是已确认的，哪些只是传闻、官方口径、社群反馈或缺失信息。

Prompt 约束：

```text
不要降低或重评风险等级，只识别不确定性边界。
```

输出字段：

```text
verified_claims
unverified_claims
official_explanation
missing_information
overclaiming_risks
```

代码中还有 `_calibrate_uncertainty()`，会对常见高风险不确定性做补充：

- 如果有“官方称”“公告称”“系统维护”，补充官方口径需要继续核验。
- 如果有“社群反馈”“大量无法提款”，补充需要与链上数据和官方公告交叉验证。
- 如果有“暂停提现”，补充缺失信息：恢复时间、储备证明、第三方验证。
- 同时提示不能直接断言“跑路”或“资不抵债”。

这个 Agent 的价值是：既不低估风险，也不夸大事实。

## 10. Merge Results：合并分支结果

代码位置：`backend/app/agents/chat_agent/merge_agent.py`

并行分支结束后，`merge_results` 会把评分、分类、影响和不确定性结果整理成一个 `merged_result`。

结构如下：

```text
merged_result
  ├── scoring
  ├── classification
  ├── impact
  └── uncertainty
```

这一步本身不调用 LLM，只是结构化汇总。

## 11. Consistency Review Agent：一致性审查

代码位置：

- `backend/app/agents/chat_agent/consistency_review_agent.py`
- `backend/app/prompts/review_prompt.py`

职责：

检查多个 Agent 结果之间是否矛盾。

Prompt 中明确说：

```text
只检查结构化结果之间是否矛盾，不重新自由评分。
如果发现高危信号明显但评分偏低，只输出 structured review result，不能覆盖 score_agent 的原始评分。
```

审查重点包括：

- `risk_status = no_risk`，但 `score > 30`
- `evidence_quality = none`，但 `score > 50`
- 原文只是长期讨论，却建议立即撤资
- 没有市场数据，却写造成市场恐慌
- 已确认攻击且损失超过 1 亿美元，但评分低于 80
- 已确认攻击且存在未授权铸造、伪造资产、跨链、混币、兑换等动作，但评分低于 80

输出字段：

```text
has_conflict
review_issues
revision_suggestions
structured_review_result
```

这里的设计重点是：审查 Agent 只发现问题，不直接覆盖评分，避免又引入一个新的“拍脑袋 Agent”。

## 12. Risk Calibration Agent：规则校准

代码位置：`backend/app/agents/chat_agent/risk_calibration_agent.py`

这是整套系统里最像“风控规则引擎”的部分。

它不依赖模型重新判断，而是根据代码里的硬规则校准风险分和状态。

关键原则：

```text
risk_score 表示事件风险严重性。
confidence_score 表示信息可信度。
不确定性只能降低 confidence_score，不能直接降低 risk_score。
不得因官方尚未确认、信息来源有限、仍在发展中而把高危攻击事件降为中风险。
```

典型硬规则：

1. 已发生攻击 + 大额资产异常 + 资金外流/跨链/兑换/Tornado Cash/mixer  
   `risk_score` 不得低于 85。

2. 已确认攻击且损失超过 1 亿美元  
   `risk_score` 不得低于 80。

3. 已确认攻击且伪造/铸造资产敞口超过 5000 万美元  
   `risk_score` 不得低于 80。

4. 交易所暂停提现 + 大量无法提款反馈  
   `risk_score` 不得低于 70，并把 `risk_status` 校准为 `confirmed_risk`。

5. 证据弱或缺失时  
   降低 `confidence_score`，但不直接降低事件严重性。

输出字段：

```text
risk_score
final_risk_score
severity_score
confidence_score
urgency_score
contagion_score
risk_level
score_reason
score_factors
calibration_rules
calibrated_result
```

汇报时可以重点强调：这是金融风控系统和普通聊天机器人的差异。高危红线不能完全交给 LLM 自由发挥，所以我们用规则做底线保护。

## 13. 生成分支：解释和建议

校准完成后，工作流进入第二个并行分支：

```python
state = _run_parallel(
    state,
    {
        "risk_explanation_agent": risk_explanation_agent,
        "advice_agent": advice_agent,
    },
    GENERATION_BRANCH_FIELDS,
)
```

### 13.1 Risk Explanation Agent

代码位置：

- `backend/app/agents/chat_agent/risk_explanation_agent.py`
- `backend/app/prompts/explanation_prompt.py`

职责：

生成一句适合聊天窗口展示的风险结论。

Prompt 约束：

```text
只解释已确定的风险评分、风险等级和风险类别。
不允许修改 risk_score、risk_level、risk_categories。
risk_explanation 最多 80 个中文字符，只写一句事件结论。
```

这个 Agent 只负责表达，不负责重新判断。

### 13.2 Advice Agent

代码位置：

- `backend/app/agents/chat_agent/advice_agent.py`
- `backend/app/prompts/advice_prompt.py`

职责：

生成风控建议。

Prompt 约束：

```text
建议不得包含直接投资指令，例如买入、卖出、做空、梭哈。
对 potential_risk / discussion_only / no actual impact，应以监测、核验、关注官方信息为主。
只有 confirmed_risk 或 systemic_risk 且证据充分时，才能建议降低暴露、暂停交互等更强动作。
不允许重新判断风险等级、评分或类别。
```

输出字段：

```text
advice
priority
action_type
```

汇报时可以说：建议 Agent 专门负责“怎么处置”，但它受到合规约束，不输出直接投资指令。

## 14. Report Agent：最终报告汇总

代码位置：

- `backend/app/agents/chat_agent/report_agent.py`
- `backend/app/prompts/report_prompt.py`

当前实现中，`report_agent` 主要在代码里汇总结构化字段，保证最终报告稳定符合前端 `RiskReport` schema。

最终输出包括：

```text
summary
input_type
has_risk
risk_status
risk_score
final_risk_score
risk_level
confidence_score
confidence_level
risk_categories
primary_category
secondary_categories
supporting_evidence
counter_evidence
missing_info
confirmed_facts
uncertainty_points
impact
affected_entities
affected_assets
advice
calibration_rules
raw_agent_outputs
```

代码位置：`backend/app/schemas.py`

`RiskReport` 用 Pydantic 定义了字段类型和默认值。这样前端展示不会因为某个 Agent 少返回字段就崩溃。

## 15. LLM 调用方式

代码位置：`backend/app/llm.py`

系统通过 DeepSeek API 调用模型：

```python
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
```

JSON 调用函数：

```python
def call_llm_json(prompt: str, temperature: float = 0.2) -> dict[str, object]:
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是严格输出 JSON 的加密货币金融风控助手。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )
```

这里还有 `_extract_json()`，用于从模型返回内容中提取 JSON，增强容错能力。

如果没有配置 API key，或者启用了离线模式，代码不会直接崩溃，而是返回错误字段。这对黑客松演示很重要。

## 16. 为什么这样设计 Agent

### 16.1 不用一个大 Agent 一次性回答

如果只用一个大 prompt，问题是：

- 评分、分类、证据、建议混在一起，难以排查。
- 模型可能先入为主。
- 前端难以展示结构化信息。
- 高危事件容易被自然语言中的“不确定”表达拉低评分。

所以我们拆成多个 Agent：

```text
分诊 Agent：有没有风险
证据 Agent：证据是什么
评分 Agent：严重性多少
分类 Agent：属于哪类风险
影响 Agent：影响谁
不确定性 Agent：哪些不能确定
审查 Agent：结果之间是否矛盾
校准 Agent：硬规则兜底
解释 Agent：怎么给用户说
建议 Agent：应该怎么处置
报告 Agent：统一输出给前端
```

### 16.2 证据驱动

系统先抽取证据，再做评分和分类。

这样可以避免模型直接凭关键词判断。例如文本里出现“攻击”不一定就是已发生攻击，可能只是讨论潜在攻击；文本里出现“官方维护”也不能自动认为没有风险，因为暂停提现本身已经影响用户资产可得性。

### 16.3 风险严重性和信息置信度分开

这是评分设计的重点。

例如：

一条新闻说“某协议疑似被攻击，损失 1 亿美元，但官方尚未确认”。

不能因为“官方尚未确认”就把风险严重性降成低风险。更合理的做法是：

- `risk_score` 高：因为如果属实，事件严重。
- `confidence_score` 中或低：因为信息还没完全核实。

这就是代码里强调的：

```text
不确定性只能降低 confidence_score，不能直接降低 risk_score。
```

### 16.4 LLM + 规则混合

LLM 擅长：

- 理解自然语言
- 抽取证据
- 总结影响
- 生成解释和建议

规则擅长：

- 高危事件下限
- 禁止投资指令
- 固定风险类别
- 字段范围校验
- 演示稳定性

所以系统不是完全依赖 LLM，而是 LLM 负责语义，规则负责底线。

## 17. 可以给导师这样讲

可以按下面这段汇报：

> 我们的 Chat Agent 不是一个单轮问答机器人，而是一个证据驱动的风控 Multi-Agent 工作流。用户输入一条加密货币风险文本后，系统先用规则工具做输入预处理，识别币种、交易所、公链、钱包地址、关键词和来源。然后第一层 `risk_triage_agent` 做风险分诊，只判断风险状态，不评分。接着 `evidence_agent` 抽取支持证据、反证、已确认事实和缺失信息。  
>
> 在证据基础上，系统并行运行四个分析 Agent：`score_agent` 做风险评分，`classify_agent` 做风险分类，`impact_agent` 做影响分析，`uncertainty_agent` 做不确定性识别。并行结果合并后，`consistency_review_agent` 检查结构化矛盾，`risk_calibration_agent` 根据风控硬规则做评分下限和状态校准。最后，`risk_explanation_agent` 生成一句风险解释，`advice_agent` 生成处置建议，`report_agent` 汇总成前端可展示的结构化报告。  
>
> 这个设计的核心是把风险严重性和信息置信度分开。高危攻击、暂停提现、大额损失、未授权铸造、资金外流等事件不能因为“信息仍在发展中”就被降为低风险；不确定性主要降低 `confidence_score`，而不是直接降低 `risk_score`。因此系统既能保持谨慎，又不会漏报重大风险。

## 18. 导师可能追问的问题

### Q1：你们的 Multi-Agent 和普通 prompt 有什么区别？

普通 prompt 是一次性让模型完成所有事情。我们的系统是多个专职 Agent 分工，每个 Agent 有明确输入、输出和 prompt 约束，并通过 `CryptoRiskState` 传递结构化结果。

### Q2：为什么要先做 evidence_agent？

因为金融风控必须可解释。先抽证据，再评分和分类，可以让每个结论都有依据，也能防止模型只靠关键词误判。

### Q3：为什么要有 risk_calibration_agent？

因为 LLM 有时会因为“官方尚未确认”“信息不足”等表述过度保守。但在风控场景中，高危事件必须有硬规则兜底。例如已确认攻击、大额损失、资金外流、暂停提现等，都需要评分下限。

### Q4：为什么评分里有 risk_score 和 confidence_score？

`risk_score` 表示事件本身的严重性，`confidence_score` 表示当前信息可信度。一个事件可以“严重性高但置信度中等”，这比简单给一个总分更适合金融风控。

### Q5：如何避免 Agent 幻觉？

主要靠四层约束：

1. 公共 prompt 要求必须阅读原文，不能编造事实。
2. 证据 Agent 要分离支持证据、反证和缺失信息。
3. 不确定性 Agent 专门识别不能过度断言的内容。
4. 规则校准和 Pydantic schema 保证字段范围和输出结构。

## 19. 可展示的核心代码清单

汇报时可以打开这些文件：

```text
backend/main.py
backend/app/agents/chat_agent/graph.py
backend/app/state.py
backend/app/tools/chat_tools.py
backend/app/prompts/common.py
backend/app/prompts/triage_prompt.py
backend/app/prompts/evidence_prompt.py
backend/app/prompts/score_prompt.py
backend/app/agents/chat_agent/risk_calibration_agent.py
backend/app/agents/chat_agent/report_agent.py
backend/app/schemas.py
```

建议展示顺序：

1. 先展示 `backend/main.py` 里的 `/api/chat`
2. 再展示 `graph.py` 里的完整 workflow
3. 再展示 `state.py` 里的 `CryptoRiskState`
4. 再展示 `common.py` 和几个 prompt
5. 最后展示 `risk_calibration_agent.py` 的硬规则

这样导师能很快看到：系统不是只有概念，而是代码里已经拆出了完整的风控 Agent 链路。
