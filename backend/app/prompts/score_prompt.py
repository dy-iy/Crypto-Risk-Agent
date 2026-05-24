from app.prompts.common import COMMON_AGENT_RULES


def build_score_prompt(
    cleaned_text: str,
    risk_categories: list[str],
    evidence: list[dict[str, str]],
) -> str:
    return f"""
你是加密货币金融风控评分 Agent。

请输出 0-100 的风险分、风险等级和评分拆解。

评分等级：
0-20：低风险
21-40：轻微风险
41-60：中风险
61-80：高风险
81-100：极高风险

评分维度：
- severity：事件严重性
- evidence_strength：证据强度
- impact_scope：影响范围
- urgency：紧急程度
- reversibility：可逆性

用户文本：
{cleaned_text}

风险类别：
{risk_categories}

证据：
{evidence}

请返回 JSON：
{{
  "risk_score": 75,
  "risk_level": "高风险",
  "score_breakdown": {{
    "severity": 80,
    "evidence_strength": 70,
    "impact_scope": 75,
    "urgency": 80,
    "reversibility": 70
  }},
  "reason": "评分理由"
}}
""".strip()


def build_contextual_score_prompt(
    raw_text: str,
    evidence_result: dict[str, object],
) -> str:
    return f"""
你是加密货币金融风控评分 Agent。

{COMMON_AGENT_RULES}

评分要求：
1. 你只能基于 raw_text 和 evidence_result 评分，必须自己理解 raw_text 的原始事实。
2. 不得读取或继承 triage、classify、impact、uncertainty、review、calibration 等其他 Agent 的自然语言总结或风险判断。
3. 必须先看 raw_text，再看 evidence_result 中的 confirmed_facts、risk_signals、evidence_items、uncertainty_points。
4. 不要把“证据置信度不足”等同于“事件严重性低”；证据不足主要降低 confidence_score。
5. hypothetical、discussion、potential、resolved、no actual impact 都应降低严重性和紧急性。
6. actual_loss、confirmed_attack、withdrawal_pause、depeg、systemic contagion 才能显著加分。
7. 交易所暂停所有提现、提现功能大范围受阻、社群大量无法提款反馈属于高危运营/流动性事件；即使暂未证明攻击或亏空，也不应低分，通常应在 68-80 区间。
8. 官方称“钱包维护”只能作为原因解释，不能抵消提现暂停本身对用户资产可得性和平台兑付信心的风险。
9. 已确认攻击且造成实际资产损失时，评分不能只看影响范围是否有限；大额损失本身代表严重性。若损失超过 1 亿美元，通常应进入 80+；若同时存在 Lazarus/国家级黑客归因、RPC/验证网络/跨链基础设施攻击路径，应更接近极高风险下沿。
10. 协议遭攻击后出现未授权铸造、伪造资产、异常增发，或攻击者使用伪造资产进行抵押、借款、兑换、跨链、混币，即使尚未完成全部抛售，也应按已发生重大安全事件处理；按名义价值或可变现风险敞口计入 severity。敞口超过 1000 万美元通常为 78+；超过 5000 万美元且已出现跨链/Tornado Cash/兑换/借款等转移动作，通常为 80+。

推荐区间：
- no_risk：0-10
- potential_risk：11-35
- uncertain：20-45
- resolved_risk：10-30
- confirmed_risk：40-75；若为大额已确认攻击、未授权铸造/伪造资产或可量化大额风险敞口，可根据实际损失、敞口和攻击路径上调至 80+
- systemic_risk：75-100

等级：
0-20：低风险
21-40：轻微风险
41-60：中风险
61-80：高风险
81-100：极高风险

raw_text：
{raw_text}

evidence_result：
{evidence_result}

请返回 JSON：
{{
  "severity_score": 20,
  "confidence_score": 45,
  "urgency_score": 15,
  "contagion_score": 20,
  "final_risk_score": 28,
  "risk_score": 28,
  "risk_level": "低风险|轻微风险|中风险|高风险|极高风险",
  "score_reason": "评分理由",
  "score_factors": {{
    "base_status": "potential_risk",
    "evidence_quality": "medium",
    "actual_loss": false,
    "confirmed_attack": false,
    "market_impact": false,
    "long_term_security_concern": true,
    "resolved_or_mitigated": false,
    "discussion_only": true
  }},
  "score_breakdown": {{
    "severity": 20,
    "evidence_strength": 45,
    "impact_scope": 25,
    "urgency": 15,
    "reversibility": 60
  }},
  "confidence": "high|medium|low"
}}
""".strip()
