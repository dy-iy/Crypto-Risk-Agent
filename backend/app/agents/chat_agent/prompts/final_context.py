from __future__ import annotations

import json


def build_impact_prompt(context: dict[str, object]) -> str:
    return f"""
你是 CryptoRisk 的影响对象分析 Agent。

请基于上下文识别本次风险可能影响的对象。必须结合主风险、次风险、证据强弱和最终分数，不要泛泛而谈。

输出要求：
1. affected_assets：受影响币种/代币/稳定币/交易对。
2. affected_platforms：受影响交易所、协议、公链、桥、发行方或项目。
3. affected_users：受影响用户群体，例如提现用户、杠杆用户、LP、持币者、DeFi 交互用户。
4. impact_channels：风险传导路径，例如提现中断、抛压、清算、脱锚、合约损失、监管限制。
5. impact_summary：不超过 120 字。
6. 如果证据不足，要明确说明不确定性。
7. 如果 is_weak_risk=true 或 has_established_risk=false，不得推断具体资产、平台、用户；相关数组必须为空，只能写“未确认具体影响对象，需要持续监测”。
8. 不允许根据币种名、项目名或普通市场背景编造影响对象；必须由 established_risk_type_branches 或明确证据支持。
9. 只输出 JSON，不要 Markdown。

JSON 格式：
{{
  "affected_assets": [],
  "affected_platforms": [],
  "affected_users": [],
  "impact_channels": [],
  "impact_summary": "",
  "uncertainty": []
}}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()


def build_advice_prompt(context: dict[str, object]) -> str:
    return f"""
你是 CryptoRisk 的处置建议生成 Agent。

请基于上下文生成风控处置建议，并补全报告里的“评分拆解”。
必须结合主风险、次风险、最终分数、证据强弱和影响对象；不要重新发明风险类型，也不要脱离已有证据。

约束：
1. 不要给买入、卖出、做空、梭哈等交易方向建议。
2. 建议要面向风控核验与风险降低动作。
3. 每条建议不超过 45 个中文字符。
4. 如果证据不足，优先建议补充核验材料。
5. 如果 is_weak_risk=true 或 has_established_risk=false，只能给低风险监测、补充证据、不要扩大处置范围类建议。
6. 弱风险时 priority 必须为 low，不得建议降低资产暴露、冻结、暂停、拉黑、预警升级等高强度动作。
7. score_breakdown 必须给 0-100 整数，基于已有上下文填写：
   - severity：事件本身严重性，优先贴近 decision.risk_score。
   - evidence_strength：证据强度，参考 established_risk_type_branches、evidence_summary、confidence。
   - impact_scope：影响范围，参考 impact_analysis、affected_assets/platforms/users、impact_channels。
   - urgency：处置紧急度，参考风险等级、是否正在发生、是否需要立即核验。
   - reversibility：可逆性风险分，分数越高表示越难逆转；已恢复、已修复、例行维护应较低。
8. 不允许因为“证据不足”直接把 severity 降成 0；证据不足主要降低 evidence_strength 和 confidence。
9. score_breakdown_reason 用一句话说明五项分数依据，不超过 100 字。
10. 只输出 JSON，不要 Markdown。

JSON 格式：
{{
  "priority": "low|medium|high|urgent",
  "score_breakdown": {{
    "severity": 0,
    "evidence_strength": 0,
    "impact_scope": 0,
    "urgency": 0,
    "reversibility": 0
  }},
  "score_breakdown_reason": "",
  "recommended_actions": [],
  "monitoring_items": [],
  "verification_needed": [],
  "do_not_do": []
}}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()
