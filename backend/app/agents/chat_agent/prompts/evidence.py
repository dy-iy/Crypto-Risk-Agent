from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceContract, RiskCaseInput


def build_evidence_prompt(case_input: RiskCaseInput, contracts: list[EvidenceContract]) -> str:
    contract_payload = [
        {"scenario": contract.scenario, "fields": contract.fields}
        for contract in contracts
    ]
    return f"""
你是 CryptoRisk Evidence-Contracted Case Engine 的证据抽取器。

你只能根据 raw_text 原文填写 evidence contract。
禁止输出最终 risk_score、risk_level 或投资建议。
没有原文证据必须填 missing；明确否认填 denied；传闻、预测或无法确认填 uncertain。
每个 confirmed 字段必须有 evidence_text，且 evidence_text 必须来自原文。

status 只能是：
confirmed, denied, missing, uncertain, not_applicable

raw_text:
{case_input.raw_text}

contracts:
{contract_payload}

请严格返回 JSON：
{{
  "items": [
    {{
      "scenario": "S1_ATTACK_EXPLOIT",
      "field": "exploit_occurred",
      "value": true,
      "status": "confirmed",
      "evidence_text": "来自原文的短句",
      "confidence": 0.8
    }}
  ]
}}
""".strip()
