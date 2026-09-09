from __future__ import annotations

import json

from app.agents.chat_agent.core.risk_fields import SCENARIO_FIELDS
from app.agents.chat_agent.schemas import RiskCaseInput, SignalScanResult
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_SCENARIO_MAP


MAX_EVIDENCE_ITEMS = 3
MAX_EVIDENCE_CHARS = 90


def build_branch_prompt(case_input: RiskCaseInput, signal_scan: SignalScanResult, risk_type: str) -> str:
    scenario = RISK_SCENARIO_MAP[risk_type]
    fields = SCENARIO_FIELDS[scenario]
    payload = {
        "risk_type": risk_type,
        "risk_name": RISK_NAME_MAP[risk_type],
        "scenario": scenario,
        "rule_score_100": int(round(float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) * 100)),
        "raw_text": case_input.raw_text,
        "entities": case_input.entities,
        "fields_to_check": fields,
    }
    return f"""
你是 CryptoRisk 的单风险类型证据审核 Agent。

你只负责一个 risk_type：{risk_type}（{RISK_NAME_MAP[risk_type]}）。
请理解整篇新闻，判断该 risk_type 是否真实成立，并提取支撑/反向证据。

硬性要求：
1. 证据必须是“理解后的概括”，不要完整摘抄原文字段或长句。
2. evidence_summary 最多 {MAX_EVIDENCE_ITEMS} 条，每条不超过 {MAX_EVIDENCE_CHARS} 个中文字符。
3. field_evidence.evidence_text 也必须是短概括，不要粘贴原文长句。
4. 如果只是传闻、预测、观点、例行维护、内部归集、已恢复、无损失，请降低 established、severity_score 和 evidence_strength。
5. 缺少关键事实时，missing_evidence 要指出缺什么；证据不足时 severity_score 不应高。
6. 评分锚点：普通讨论/上线/交易竞赛/正向流入 <=25；明确风险机制但无实际损失 25-45；实际流出、强平、坏账、连续暴跌、服务停止 50-75；攻击、脱锚、大规模清算、重大坏账 >=80。
7. 类别仲裁：清算/强平优先于巨鲸或攻击误判；跨链桥关闭/停止转账优先于交易所运维；市场暴跌优先于宏观，除非原文明确说明由宏观事件驱动。
8. 不要给交易建议，不要输出 Markdown，只能输出 JSON。

JSON 格式：
{{
  "risk_type": "{risk_type}",
  "established": true,
  "severity_score": 65,
  "evidence_strength": 70,
  "confidence": 0.72,
  "evidence_summary": ["短证据概括1", "短证据概括2"],
  "missing_evidence": ["缺少官方确认"],
  "field_evidence": [
    {{
      "field": "{fields[0]}",
      "value": true,
      "status": "confirmed",
      "evidence_text": "短概括，不照抄原文",
      "confidence": 0.75
    }}
  ],
  "reasoning": "一句话说明该分支为什么成立或不成立"
}}

输入：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()
