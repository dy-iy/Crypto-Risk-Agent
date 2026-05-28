# CryptoRisk Evidence-Contracted Case Engine v6 实现报告

本文档用于审核当前项目中 v6 新框架的实现细节。报告覆盖架构目标、生产调用链、模块职责、数据结构、证据契约、场景评分卡、决策规则、验证机制、前端兼容、fallback 策略、评测集和当前局限。

---

## 1. 最终架构定位

当前 `/api/chat` 的核心风险分析链路已经从旧的 multi-agent workflow 切换为：

```text
CryptoRisk Evidence-Contracted Case Engine
证据契约驱动的加密资产风险案件引擎
```

核心原则：

```text
以风险案件为核心
以证据契约约束 LLM
以场景评分卡做裁决
以问题式验证降低误判
以评测集持续校准
```

一句话实现原则：

```text
LLM 不直接决定最终 risk_score。
LLM 只负责填 evidence contract。
最终风险分、风险等级、风险状态由 Python 场景评分卡和 Decision Policy Engine 决定。
```

---

## 2. 当前接入状态

### 2.1 API 入口

FastAPI 入口仍保持不变：

```text
POST /api/chat
```

入口文件：

```text
backend/main.py
```

接口仍然调用：

```python
run_chat_agent(request.message)
```

### 2.2 v6 接入点

接入位置：

```text
backend/app/agents/chat_agent/graph.py
```

当前 `run_chat_agent()` 逻辑：

```text
USE_CHAT_AGENT=true 或未设置
  -> 优先调用 run_chat_agent(user_message)

v6 成功
  -> 返回 v6 report

v6 抛异常
  -> 默认 fallback 到旧 chat_workflow

USE_CHAT_AGENT=false
  -> 直接走旧 workflow

CHAT_AGENT_STRICT=true
  -> v6 报错时不 fallback，直接抛出，方便调试
```

这保证了：

```text
新框架默认启用
旧 pipeline 仍保留
接口不会因为 v6 单点异常直接崩溃
```

---

## 3. 新增文件结构

v6 核心代码位于：

```text
backend/app/agents/chat_agent/
```

当前文件：

```text
backend/app/agents/chat_agent/__init__.py
backend/app/agents/chat_agent/schemas.py
backend/app/agents/chat_agent/normalizer.py
backend/app/agents/chat_agent/signal_scanner.py
backend/app/agents/chat_agent/orchestrator.py
backend/app/agents/chat_agent/scenario_router.py
backend/app/agents/chat_agent/evidence_contracts.py
backend/app/agents/chat_agent/evidence_extractor.py
backend/app/agents/chat_agent/decision_engine.py
backend/app/agents/chat_agent/validator.py
backend/app/agents/chat_agent/report_generator.py
backend/app/agents/chat_agent/pipeline.py
backend/app/agents/chat_agent/README.md
```

场景评分卡位于：

```text
backend/app/agents/chat_agent/scenario_evaluators/
```

当前评分卡：

```text
s0_general.py
s1_attack.py
s2_exchange.py
s3_stablecoin.py
s4_infra.py
s5_regulatory.py
s6_market.py
s7_fraud.py
s8_whale.py
```

离线评测位于：

```text
backend/evals/risk_cases_smoke.jsonl
backend/evals/run_risk_eval.py
```

---

## 4. 生产链路实现

生产链路入口：

```text
backend/app/agents/chat_agent/pipeline.py
```

主函数：

```python
run_chat_agent(message: str) -> dict[str, object]
```

完整流程：

```text
Input
  ↓
Input Normalizer
  ↓
Fast Signal Scan
  ↓
Adaptive Orchestrator
  ├─ Fast Exit
  ├─ Standard Analysis
  └─ Validation Path
  ↓
Scenario Hypothesis Router
  ↓
Evidence Contract Builder
  ↓
Targeted Evidence Extraction
  ↓
Parallel Scenario Evaluators
  ↓
Decision Policy Engine
  ↓
Question-based Conflict Validator
  ↓
Decision Policy Engine apply validation
  ↓
Report Generator
```

实际代码调用顺序：

```python
case_input = normalize_input(message)
signal_scan = scan_fast_signals(case_input.content)
orchestration = choose_path(signal_scan)

if orchestration.path == "fast_exit":
    return _fast_exit_result(message).report

hypotheses = route_scenarios(signal_scan)
contracts = build_contracts(hypotheses)
evidence = extract_evidence(case_input, contracts)
evaluations = evaluate_scenarios(case_input, signal_scan, evidence, hypotheses)
decision = decide(signal_scan, evaluations)

if orchestration.needs_validation or need_validation(decision, evaluations):
    validation = validate_conflicts(decision, evidence)
    decision = decide(signal_scan, evaluations, validation)

report = build_report(result)
```

---

## 5. 核心数据结构

定义文件：

```text
backend/app/agents/chat_agent/schemas.py
```

### 5.1 ScenarioId

当前支持 9 个场景：

```text
S0_GENERAL_UNKNOWN
S1_ATTACK_EXPLOIT
S2_EXCHANGE_ABNORMALITY
S3_STABLECOIN_RESERVE
S4_INFRASTRUCTURE_FAILURE
S5_REGULATORY_ENFORCEMENT
S6_MARKET_LIQUIDATION
S7_FRAUD_GOVERNANCE
S8_WHALE_ONCHAIN_FLOW
```

### 5.2 EvidenceStatus

证据字段状态：

```text
confirmed
denied
missing
uncertain
not_applicable
```

### 5.3 RiskCaseInput

标准化输入：

```json
{
  "case_id": "...",
  "raw_text": "...",
  "title": "",
  "content": "...",
  "source_url": "",
  "source_name": "",
  "published_at": null,
  "language": "zh",
  "input_type": "...",
  "entities": {},
  "keyword_refs": [],
  "metadata": {}
}
```

### 5.4 SignalScanResult

规则信号扫描结果：

```json
{
  "positive_signals": [],
  "negative_signals": [],
  "cap_signals": [],
  "scenario_scores": {},
  "raw_rule_scores": {},
  "suggested_top_k": 2,
  "fast_exit_allowed": false,
  "debug": {}
}
```

### 5.5 EvidenceFieldResult

证据契约字段：

```json
{
  "scenario": "S7_FRAUD_GOVERNANCE",
  "field": "phishing_site",
  "value": true,
  "status": "confirmed",
  "evidence_text": "原文证据片段",
  "confidence": 0.76
}
```

### 5.6 ScenarioEvaluation

场景评分卡输出：

```json
{
  "scenario": "S7_FRAUD_GOVERNANCE",
  "is_applicable": true,
  "scenario_score": 70,
  "confidence": 0.82,
  "severity": "medium_high",
  "score_cap": null,
  "score_floor": null,
  "reason_codes": [],
  "missing_evidence": [],
  "evidence_summary": []
}
```

### 5.7 DecisionResult

最终裁决结果：

```json
{
  "risk_score": 70,
  "risk_level": "中高风险",
  "risk_status": "confirmed_risk",
  "primary_scenario": "S7_FRAUD_GOVERNANCE",
  "secondary_scenarios": [],
  "confidence": 0.65,
  "reason_codes": [],
  "score_caps_applied": [],
  "score_floors_applied": []
}
```

---

## 6. Input Normalizer

实现文件：

```text
backend/app/agents/chat_agent/normalizer.py
```

职责：

```text
清洗输入文本
生成 case_id
检测语言
复用旧 prepare_chat_input 抽取 entities / keyword_refs / source_hint
输出 RiskCaseInput
```

实现细节：

```text
case_id = sha256(cleaned_text)[:16]
language = 含中文则 zh，否则 en
entities / keyword_refs 复用 backend/app/tools/chat_tools.py
```

复用旧逻辑的原因：

```text
旧 input tool 已经能识别钱包地址、ticker、交易所、公链和关键词上下文。
这些属于低风险、确定性预处理逻辑，可以继续复用。
```

---

## 7. Fast Signal Scan

实现文件：

```text
backend/app/agents/chat_agent/signal_scanner.py
```

### 7.1 规则脚本迁移

旧规则脚本：

```text
backend/app/tools/risk_score and risk_type labler.py
```

已完成改造：

```text
去掉 import 时读取 CSV 的副作用
去掉 import 时写 CSV 的副作用
保留 score_hack / score_fraud / score_regulatory 等规则函数
批处理 CSV 逻辑移动到 run_batch() 和 if __name__ == "__main__"
```

v6 通过 `importlib.util.spec_from_file_location` 加载它，并调用：

```python
score_all_risks(text)
```

注意：

```text
旧规则的 risk / rule_label / rule_primary_type 只作为 debug。
不会直接成为最终 risk_score。
```

### 7.2 规则到场景映射

映射关系：

```text
score_hack        -> S1_ATTACK_EXPLOIT
score_outage      -> S2_EXCHANGE_ABNORMALITY
score_stablecoin  -> S3_STABLECOIN_RESERVE
score_regulatory  -> S5_REGULATORY_ENFORCEMENT
score_liquidation -> S6_MARKET_LIQUIDATION
score_volatility  -> S6_MARKET_LIQUIDATION
score_infra       -> S4_INFRASTRUCTURE_FAILURE
score_fraud       -> S7_FRAUD_GOVERNANCE
score_team        -> S7_FRAUD_GOVERNANCE
score_whale       -> S8_WHALE_ONCHAIN_FLOW
score_solvency    -> S3_STABLECOIN_RESERVE
score_macro       -> S0_GENERAL_UNKNOWN
```

### 7.3 负向信号

当前负向信号：

```text
planned_maintenance
resolved_or_repaired
no_loss_or_no_impact
discussion_only
security_research_only
internal_transfer
rumor_without_confirmation
normal_market_commentary
positive_regulatory_clarity
ordinary_team_change
```

### 7.4 分数封顶信号

当前 cap 规则：

```text
security_research_only -> cap 45
planned_maintenance -> cap 45
resolved_or_repaired -> cap 40
discussion_only -> cap 35
internal_transfer -> cap 30
rumor_without_confirmation -> cap 55
normal_market_commentary -> cap 25
positive_regulatory_clarity -> cap 20
ordinary_team_change -> cap 35
```

这些 cap 不直接修改最终分，而是传给 Decision Engine，由 Decision Engine 统一执行。

### 7.5 额外正向规则

为覆盖旧脚本召回不足的演示场景，新增额外正向模式：

```text
phishing_or_fake_airdrop -> S7_FRAUD_GOVERNANCE
rug_or_exit -> S7_FRAUD_GOVERNANCE
infra_failure -> S4_INFRASTRUCTURE_FAILURE
whale_exchange_flow -> S8_WHALE_ONCHAIN_FLOW
```

例如：

```text
钓鱼网站 / 假空投 / 虚假空投 / 冒充 / 假代币 -> S7
停止出块 / 预言机异常 / RPC 故障 / 节点故障 -> S4
巨鲸 / 大额转账 / 转入交易所 / 链上监测 -> S8
```

---

## 8. Adaptive Orchestrator

实现文件：

```text
backend/app/agents/chat_agent/orchestrator.py
```

输出：

```text
fast_exit
standard_analysis
validation_path
```

### 8.1 Fast Exit

条件：

```text
signal_scan.fast_exit_allowed = true
```

结果：

```text
不调用 LLM
直接返回 S0 低风险
risk_score = 10
risk_status = low_risk
```

### 8.2 Validation Path

触发条件：

```text
高危场景信号 >= 0.5
或强规则信号与 cap signal 同时存在
```

高危场景集合：

```text
S1_ATTACK_EXPLOIT
S2_EXCHANGE_ABNORMALITY
S3_STABLECOIN_RESERVE
S5_REGULATORY_ENFORCEMENT
```

---

## 9. Scenario Hypothesis Router

实现文件：

```text
backend/app/agents/chat_agent/scenario_router.py
```

职责：

```text
根据 signal_scan.scenario_scores 排序
选择 Top-K 场景
永远追加 S0_GENERAL_UNKNOWN 兜底
```

Top-K 由 Fast Signal Scan 生成：

```text
弱信号：Top-1
普通信号：Top-2
复杂信号：Top-3 / Top-4
```

输出格式：

```json
{
  "scenario": "S7_FRAUD_GOVERNANCE",
  "hypothesis": "文本可能描述欺诈、跑路、团队异常或治理风险。",
  "priority": 1,
  "required_fields": []
}
```

---

## 10. Evidence Contract Builder

实现文件：

```text
backend/app/agents/chat_agent/evidence_contracts.py
```

### 10.1 S0 General / Unknown

字段：

```text
article_type
source_type
risk_signal_summary
why_no_specific_scenario
insufficient_evidence_reason
```

### 10.2 S1 Attack / Exploit

字段：

```text
exploit_occurred
attack_vector
loss_usd
user_fund_affected
attacker_address
mitigation_status
is_security_research_only
is_historical_event
official_confirmation
```

### 10.3 S2 Exchange Abnormality

字段：

```text
withdrawal_suspended
deposit_suspended
trading_halted
withdrawal_delay_only
official_notice
planned_maintenance
recovery_time
fund_safety_statement
already_resolved
affected_assets
affected_exchange
```

### 10.4 S3 Stablecoin / Reserve

字段：

```text
stablecoin_name
depeg_mentioned
depeg_price
reserve_issue
redemption_suspended
issuer_statement
duration_mentioned
```

### 10.5 S4 Infrastructure Failure

字段：

```text
network_outage
block_production_stopped
oracle_failure
bridge_paused
rpc_or_node_failure
affected_chain_or_protocol
user_transactions_affected
funds_at_risk
already_resolved
```

### 10.6 S5 Regulatory Enforcement

字段：

```text
regulator
target_entity
enforcement_action
penalty_or_freeze
lawsuit_or_charge
jurisdiction
legal_status
is_policy_discussion_only
is_positive_regulatory_clarity
```

### 10.7 S6 Market / Liquidation

字段：

```text
price_drop_pct
time_window
liquidation_amount_usd
market_scope
is_major_asset
is_normal_market_commentary
is_forecast_only
liquidity_stress_mentioned
```

### 10.8 S7 Fraud / Governance

字段：

```text
phishing_site
fake_airdrop
impersonation
fake_token
wallet_connection_lure
user_loss_confirmed
fraud_claim
rug_pull_or_exit
team_missing
funds_removed
official_response
is_ordinary_team_change
```

### 10.9 S8 Whale / On-chain Flow

字段：

```text
large_transfer
to_exchange
from_exchange
amount_usd
token_or_asset
internal_transfer
wallet_address
sell_pressure_indicated
```

---

## 11. Targeted Evidence Extraction

实现文件：

```text
backend/app/agents/chat_agent/evidence_extractor.py
```

### 11.1 LLM Prompt 约束

Prompt 明确要求：

```text
只能根据 raw_text 填 evidence contract
禁止输出最终 risk_score
禁止输出 risk_level
没有证据填 missing
明确否认填 denied
传闻/预测/无法确认填 uncertain
confirmed 字段必须带 evidence_text
```

返回 JSON：

```json
{
  "items": [
    {
      "scenario": "S7_FRAUD_GOVERNANCE",
      "field": "phishing_site",
      "value": true,
      "status": "confirmed",
      "evidence_text": "来自原文的短句",
      "confidence": 0.8
    }
  ]
}
```

### 11.2 Pydantic 校验

LLM 输出先进入内部模型：

```python
_LLMEvidenceResponse
_LLMEvidenceItem
```

再转换为正式：

```python
EvidenceExtractionResult
EvidenceFieldResult
```

校验规则：

```text
忽略未知 scenario
忽略未知 field
非法 status 降级为 missing
confirmed 但无 evidence_text 时改为 uncertain
未返回字段自动补 missing
```

### 11.3 LLM 不可用 fallback

如果：

```text
DEEPSEEK_API_KEY 未配置
openai 包未安装
LLM JSON 解析失败
LLM 调用异常
```

系统不会炸穿 `/api/chat`，而是：

```text
使用 _fallback_items()
基于本地启发式规则填部分 EvidenceFieldResult
记录 extraction_errors
继续进入 Python 评分卡
```

这也是当前 smoke eval 能在无 DeepSeek 调用环境下运行的原因。

---

## 12. Scenario Evaluators

实现目录：

```text
backend/app/agents/chat_agent/scenario_evaluators/
```

统一入口：

```text
base.py -> evaluate_scenarios()
```

并行方式：

```python
ThreadPoolExecutor(max_workers=max(1, min(4, len(hypotheses))))
```

每个 evaluator：

```text
只读取 case_input / signal_scan / evidence
不调用 LLM
不读取其他 evaluator 输出
输出 ScenarioEvaluation
```

### 12.1 S0 General / Unknown

文件：

```text
s0_general.py
```

逻辑：

```text
弱规则信号 -> score 10, confidence 0.75
有弱风险但无具体场景 -> score 28, confidence 0.45
```

### 12.2 S1 Attack / Exploit

文件：

```text
s1_attack.py
```

加分逻辑：

```text
exploit_occurred -> score >= 62
attack_vector -> score >= 58
loss_usd -> score >= 72
user_fund_affected -> +8
```

floor：

```text
loss_usd >= 100M -> floor 82
loss_usd >= 10M -> floor 76
```

cap：

```text
security_research_only -> cap 45
historical_event -> cap 45
mitigated_without_loss -> cap 40
official_confirmation_denied and no loss -> cap 50
```

### 12.3 S2 Exchange Abnormality

文件：

```text
s2_exchange.py
```

基础分：

```text
withdrawal_suspended -> 70
deposit_suspended -> 55
trading_halted -> 65
withdrawal_delay_only -> 45
```

加分：

```text
major_exchange -> +8
affected_assets -> +5
recovery_time_missing -> +8
fund_safety_statement_missing -> +5
```

降级：

```text
planned_maintenance -> -25, cap 45
recovery_time_confirmed -> -10
already_resolved -> -20, cap 35
fund_safety_statement -> -15
```

### 12.4 S3 Stablecoin / Reserve

文件：

```text
s3_stablecoin.py
```

逻辑：

```text
depeg_mentioned -> score 58
reserve_issue -> +18
redemption_suspended -> +18
issuer_statement -> -8
```

### 12.5 S4 Infrastructure Failure

文件：

```text
s4_infra.py
```

基础分：

```text
network_outage -> 66
block_production_stopped -> 72
oracle_failure -> 68
bridge_paused -> 58
rpc_or_node_failure -> 52
```

加分：

```text
user_transactions_affected -> +8
funds_at_risk -> +10
```

降级：

```text
already_resolved -> -25, cap 45
```

### 12.6 S5 Regulatory Enforcement

文件：

```text
s5_regulatory.py
```

高风险前提：

```text
regulator confirmed
target_entity confirmed
enforcement_action/lawsuit_or_charge confirmed
```

评分：

```text
regulator + target + action -> 72
action only -> 48
penalty_or_freeze -> +10
```

cap：

```text
policy_discussion_only -> cap 30
positive_regulatory_clarity -> cap 20
```

### 12.7 S6 Market / Liquidation

文件：

```text
s6_market.py
```

评分：

```text
price_drop_pct >= 20 -> 72
price_drop_pct >= 8 -> 50
liquidation_amount_usd >= 100M -> 76
liquidation_amount_usd >= 10M -> 58
liquidity_stress_mentioned -> +12
market_scope -> +5
```

cap：

```text
normal_market_commentary -> cap 25
forecast_only -> cap 35
```

### 12.8 S7 Fraud / Governance

文件：

```text
s7_fraud.py
```

基础分：

```text
phishing_site -> 58
fake_airdrop -> 54
impersonation -> 50
fake_token -> 48
fraud_claim -> 55
rug_pull_or_exit -> 82
```

加分 / floor：

```text
wallet_connection_lure -> +12
user_loss_confirmed -> +18, floor 70
team_missing -> +8
funds_removed -> +15, floor 72
rug_pull_or_exit -> floor 76
official_response -> +4
```

cap：

```text
is_ordinary_team_change -> cap 35
```

### 12.9 S8 Whale / On-chain Flow

文件：

```text
s8_whale.py
```

评分：

```text
large_transfer -> 32
amount_usd >= 100M -> +25
amount_usd >= 10M -> +16
amount_usd > 0 -> +8
to_exchange -> +18
sell_pressure_indicated -> +16
from_exchange -> +6
wallet_address -> +4
```

cap：

```text
internal_transfer -> cap 30
```

---

## 13. Decision Policy Engine

实现文件：

```text
backend/app/agents/chat_agent/decision_engine.py
```

职责：

```text
选择主场景
合并次级风险
执行 score_floor
执行 score_cap
应用 validator 建议
生成 risk_score / risk_level / risk_status
```

### 13.1 主场景选择

逻辑：

```text
先过滤 is_applicable=true 的 evaluations
优先从非 S0 场景中选择最高分
如果没有非 S0，则使用 S0
排序依据：scenario_score, confidence
```

这样可以避免：

```text
负向场景被 S0 抢主场景
普通维护 / 安全研究 / 监管讨论无法展示具体场景
```

### 13.2 次级风险加成

规则：

```text
其他场景 scenario_score >= 45 时，每个 +4
总加成最多 +10
```

### 13.3 floor 应用

来源：

```text
ScenarioEvaluation.score_floor
ValidationSuggestion.score_floor
```

### 13.4 cap 应用

来源：

```text
ScenarioEvaluation.score_cap
ValidationSuggestion.score_cap
SignalScanResult.cap_signals
```

执行顺序：

```text
先应用 evaluator floor/cap
再应用 validator floor/cap
最后再次应用 signal cap
```

这样保证：

```text
传闻、计划维护、普通行情、监管讨论等 cap 不会被 validator floor 反向顶高。
```

### 13.5 风险等级

当前等级：

```text
0-20: 低风险
21-40: 轻微风险
41-60: 中风险
61-75: 中高风险
76-90: 高风险
91-100: 极高风险
```

### 13.6 风险状态

当前状态：

```text
low_risk
potential_risk
confirmed_risk
insufficient_evidence
resolved_or_mitigated
false_positive_suppressed
```

判定逻辑：

```text
weak_rule_signal -> low_risk
resolved / mitigated reason -> resolved_or_mitigated
score <= 20 -> low_risk
confidence < 0.45 -> insufficient_evidence
score >= 61 -> confirmed_risk
其他 -> potential_risk
```

---

## 14. Question-based Conflict Validator

实现文件：

```text
backend/app/agents/chat_agent/validator.py
```

### 14.1 触发条件

函数：

```python
need_validation(decision, evaluations)
```

条件：

```text
decision.risk_score >= 75
decision.confidence < 0.6
存在 score_caps_applied
多个场景分数差 <= 8
```

### 14.2 Validator 输出

只能输出：

```json
{
  "action": "cap_score / raise_floor / no_change",
  "score_cap": 45,
  "score_floor": null,
  "reason": "...",
  "answered_questions": {}
}
```

Validator 不直接改最终分。最终是否应用由 Decision Engine 执行。

### 14.3 当前验证问题

S1：

```text
是否确认攻击发生
是否有损失金额
是否只是安全研究
是否已经修复/缓解
```

S2：

```text
是否暂停提现
是否计划维护
是否有恢复时间
是否说明资金安全
是否只是传闻
```

S5：

```text
是否只是监管讨论
是否是监管利好
是否有明确执法动作
```

S6：

```text
是否普通行情评论
是否预测文章
```

S4：

```text
基础设施异常是否已恢复
是否确认资金风险
是否停止出块
```

S7：

```text
是否普通团队变动
是否确认钓鱼/假空投
是否确认用户损失
```

S8：

```text
是否内部归集
是否转入交易所
是否明确卖压
```

---

## 15. Report Generator

实现文件：

```text
backend/app/agents/chat_agent/report_generator.py
```

职责：

```text
将 v6 结构化结果转成前端兼容 RiskReport
不修改风险分
保留旧字段
增加 v6_result/debug
```

### 15.1 场景到前端类别映射

```text
S0 -> 综合风险
S1 -> 链上漏洞 / 攻击风险
S2 -> 交易所与系统运维风险
S3 -> 稳定币异常风险
S4 -> 基础设施 / 协议层异常风险
S5 -> 监管与法律风险
S6 -> 爆仓 / 清算风险
S7 -> 诈骗 / 跑路 / Rug Pull 风险
S8 -> 大额转账 / 巨鲸行为风险
```

### 15.2 兼容旧前端字段

当前仍返回：

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
risk_signals
non_risk_factors
evidence
score_breakdown
impact
advice
missing_info
uncertainty_points
score_reason
calibration_rules
```

### 15.3 新增字段

新增：

```json
{
  "v6_result": {
    "engine": "CryptoRisk Evidence-Contracted Case Engine",
    "primary_scenario": "...",
    "secondary_scenarios": [],
    "confidence": 0.65,
    "orchestration_path": "validation_path",
    "validation": {}
  },
  "debug": {
    "signal_scan": {},
    "scenario_evaluations": [],
    "evidence_errors": []
  }
}
```

后端 `RiskReport` schema 已增加：

```text
v6_result: dict[str, object]
debug: dict[str, object]
```

前端 `frontend/lib/api.ts` 中的 `RiskReport` 类型也已增加可选：

```ts
v6_result?: Record<string, unknown>;
debug?: Record<string, unknown>;
```

---

## 16. LLM 与 DeepSeek 使用方式

DeepSeek 调用仍在：

```text
backend/app/llm.py
```

v6 中唯一主要 LLM 使用点：

```text
backend/app/agents/chat_agent/evidence_extractor.py
```

### 16.1 模型配置

模型配置来自环境变量：

```text
DEEPSEEK_MODEL 默认 deepseek-v4-pro
DEEPSEEK_API_KEY 从 .env 读取
DEEPSEEK_BASE_URL 默认 https://api.deepseek.com
```

### 16.2 openai 包可选化

为了保证本地评测和缺依赖环境不直接崩溃，`backend/app/llm.py` 已改成：

```text
openai 包不存在时，不在 import 阶段抛错
调用 LLM 时返回 {"_llm_error": "openai package is not installed"}
```

Evidence extractor 会接住该错误，并启用本地 fallback evidence。

---

## 17. 旧 Pipeline 保留方式

旧 pipeline 完整保留：

```text
backend/app/agents/chat_agent/
```

旧 workflow 仍然是：

```text
prepare_chat_input
risk_triage_agent
evidence_agent
parallel score/classify/impact/uncertainty
merge_results
consistency_review_agent
risk_calibration_agent
parallel explanation/advice
report_agent
```

fallback 触发：

```text
USE_CHAT_AGENT=false
或 v6 抛异常且 CHAT_AGENT_STRICT 未开启
```

---

## 18. 前端兼容情况

当前前端请求仍然是：

```text
/api/chat
```

位置：

```text
frontend/lib/api.ts
```

没有新增：

```text
localhost
127.0.0.1
8000
8001
8002
```

报告页能展示 v6 输出，是因为 v6 report 兼容了旧字段：

```text
risk_score
risk_level
confidence_score
confidence_level
risk_categories
risk_signals
evidence
impact
advice
score_breakdown
```

但前端 UI 文案仍有旧痕迹：

```text
多 Agent 正在分析
```

这是展示层未 polish，不影响后端新框架实际运行。

---

## 19. Evaluation Harness

评测脚本：

```text
backend/evals/run_risk_eval.py
```

评测集：

```text
backend/evals/risk_cases_smoke.jsonl
```

当前样例数：

```text
24
```

覆盖类型：

```text
确认攻击
漏洞披露但未攻击
安全审计报告
计划维护
提现暂停
提现传闻
监管执法
监管讨论
法院驳回 / 监管利好
稳定币脱锚
稳定币讨论
巨鲸转入交易所
交易所内部归集
行情日报
异常暴跌 / 清算
项目方跑路 / Rug Pull
普通团队变动
假空投 / 钓鱼
基础设施停止出块
预言机异常
RPC 已恢复
```

运行命令：

```bash
python3 backend/evals/run_risk_eval.py
```

最近一次验证结果：

```json
{
  "total": 24,
  "valid": 24,
  "error_rate": 0.0,
  "scenario_accuracy": 1.0,
  "score_range_accuracy": 1.0,
  "high_risk_accuracy": 1.0,
  "failed_cases": []
}
```

注意：

```text
这是 smoke eval，不是正式 80-120 条评测集。
当前指标用于防止核心误判回潮，不代表生产级全面准确率。
```

---

## 20. 已验证样例

### 20.1 Jupiter 假空投 / 钓鱼

输入摘要：

```text
诈骗团伙冒充 Jupiter，向钱包空投虚假 CJUP 代币，并诱导用户连接至诈骗网站以窃取资产。
```

当前输出：

```text
risk_score = 70
risk_level = 中高风险
risk_category = 诈骗 / 跑路 / Rug Pull 风险
primary_scenario = S7_FRAUD_GOVERNANCE
```

这修复了早期问题：

```text
旧结果落到 S0 综合风险，风险分 28
```

### 20.2 巨鲸转入交易所

输入摘要：

```text
巨鲸地址向 Binance 转入价值 1.2 亿美元 BTC，市场担忧短期抛压。
```

当前输出：

```text
risk_score = 57
risk_level = 中风险
risk_category = 大额转账 / 巨鲸行为风险
primary_scenario = S8_WHALE_ONCHAIN_FLOW
```

### 20.3 基础设施停止出块

输入摘要：

```text
Evmos 将停止出块和节点运营，区块浏览器、官网无法访问。
```

当前输出：

```text
risk_score = 72
risk_level = 中高风险
risk_category = 基础设施 / 协议层异常风险
primary_scenario = S4_INFRASTRUCTURE_FAILURE
```

---

## 21. 主要安全边界

当前实现避免了以下旧问题：

### 21.1 LLM 自由打分

旧风险：

```text
score_agent 直接让 LLM 输出 risk_score
```

v6：

```text
LLM 不允许输出最终 risk_score
最终分由 Python 评分卡 + Decision Engine 决定
```

### 21.2 RAG/证据幻觉

旧风险：

```text
LLM 看了原文后自由总结证据，可能把未支持内容写成事实
```

v6：

```text
字段级 evidence contract
每个 confirmed 字段必须绑定 evidence_text
缺证据字段为 missing / uncertain
```

### 21.3 LLM-as-Judge 自由复核

旧风险：

```text
review_agent 自由判断分数是否合理
```

v6：

```text
validator 只回答固定验证问题
只输出 cap/floor 建议
最终改分仍回到 Decision Engine
```

### 21.4 关键词误伤

旧风险：

```text
命中 攻击/监管/维护/清算 就高分
```

v6：

```text
负向信号 + cap rules
security_research_only
planned_maintenance
discussion_only
internal_transfer
normal_market_commentary
positive_regulatory_clarity
```

---

## 22. 当前仍待完善项

### 22.1 排行榜尚未统一 v6

当前 `/api/chat` 已接入 v6。

但排行榜新闻增量标注仍主要使用：

```text
backend/app/services/llm_news_risk_service.py
backend/app/services/rule_risk_scorer.py
backend/app/agents/ranking_agent/
```

风险：

```text
同一条新闻在聊天分析和排行榜可能出现分数体系不一致。
```

建议下一步：

```text
把排行榜 fallback 或 LLM 标注也改为调用 v6 pipeline 的轻量适配器。
```

### 22.2 前端展示仍有旧 multi-agent 文案

当前页面可能还显示：

```text
多 Agent 正在分析
证据抽取 / 风险分类 / 评分拆解 / 报告生成
```

建议改为：

```text
证据契约引擎正在分析
信号扫描
证据契约填充
场景评分卡
决策校准
```

### 22.3 评测集仍是 smoke eval

当前 24 条样例用于 smoke test。

正式答辩建议扩展到：

```text
80-120 条
```

并输出：

```text
scenario_accuracy
high_risk_precision
high_risk_recall
score_mae
latency_p95
误报 Top 10
漏报 Top 10
```

### 22.4 Evidence extractor 的启发式 fallback 仍偏规则

当前在 LLM 不可用时，本地 fallback 能保证系统可运行。

但它不是完整语义抽取器。

建议：

```text
有 DeepSeek API 时以 LLM contract extraction 为主
本地 fallback 只作为兜底
```

### 22.5 v6 debug 字段前端未完整可视化

当前报告页能展示部分字段，但没有完整展示：

```text
primary_scenario
orchestration_path
validation answered_questions
score_caps_applied
score_floors_applied
```

建议加入“决策轨迹”区域，增强答辩可解释性。

---

## 23. 审核重点建议

建议审核时重点看以下文件：

```text
backend/app/agents/chat_agent/graph.py
backend/app/agents/chat_agent/pipeline.py
backend/app/agents/chat_agent/schemas.py
backend/app/agents/chat_agent/signal_scanner.py
backend/app/agents/chat_agent/evidence_contracts.py
backend/app/agents/chat_agent/evidence_extractor.py
backend/app/agents/chat_agent/scenario_evaluators/
backend/app/agents/chat_agent/decision_engine.py
backend/app/agents/chat_agent/validator.py
backend/app/agents/chat_agent/report_generator.py
backend/evals/risk_cases_smoke.jsonl
backend/evals/run_risk_eval.py
```

审核问题清单：

```text
1. 是否接受 /api/chat 默认启用 v6？
2. 是否保留 USE_CHAT_AGENT=false 的旧 pipeline fallback？
3. 是否接受当前风险等级区间？
4. 是否接受 S7 钓鱼/假空投打到中高风险？
5. 是否接受巨鲸转入交易所默认中风险，只有明确卖压/大额时升高？
6. 是否要把排行榜也统一接入 v6？
7. 是否要前端展示 v6_result/debug 的决策轨迹？
8. 是否要把 smoke eval 扩到正式评测集？
```

---

## 24. 当前结论

当前实现已经完成：

```text
/api/chat 新框架默认接入
旧 workflow fallback 保留
S0-S8 全场景覆盖
证据契约字段建模
LLM 输出 Pydantic 校验
LLM 不直接打最终分
Python 场景评分卡
Decision Engine 统一裁决
Question-based Validator 固定问题验证
前端旧字段兼容
v6_result/debug 新字段返回
24 条 smoke eval 全通过
```

当前尚未完成：

```text
排行榜统一 v6
前端新架构文案 polish
v6 决策轨迹完整可视化
80-120 条正式评测集
```

整体判断：

```text
聊天分析后端主链路已经是 v6 可落地版本。
如果目标是黑客松答辩展示，下一步应优先做前端展示 polish 和排行榜 v6 统一。
```
