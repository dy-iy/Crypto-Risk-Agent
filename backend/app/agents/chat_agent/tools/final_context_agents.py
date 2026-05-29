from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.agents.chat_agent.schemas import DecisionResult, RiskCaseInput, SignalScanResult
from app.llm import call_llm_json


def _compact(value: object, max_chars: int = 140) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _build_context(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    decision: DecisionResult,
) -> dict[str, object]:
    return {
        "raw_text": case_input.raw_text,
        "input_type": case_input.input_type,
        "entities": case_input.entities,
        "decision": decision.model_dump(),
        "raw_rule_scores": signal_scan.raw_rule_scores,
        "risk_type_stats": signal_scan.debug.get("risk_type_stats", []),
        "risk_type_branches": signal_scan.debug.get("risk_type_branches", []),
        "branch_score_merge": signal_scan.debug.get("branch_score_merge", {}),
        "low_risk_gate": signal_scan.debug.get("low_risk_gate", {}),
    }


def _impact_prompt(context: dict[str, object]) -> str:
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
7. 只输出 JSON，不要 Markdown。

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


def _advice_prompt(context: dict[str, object]) -> str:
    return f"""
你是 CryptoRisk 的处置建议生成 Agent。

请基于上下文生成风控处置建议。必须结合主风险、次风险、最终分数、证据强弱和影响对象。

约束：
1. 不要给买入、卖出、做空、梭哈等交易方向建议。
2. 建议要面向风控核验与风险降低动作。
3. 每条建议不超过 45 个中文字符。
4. 如果证据不足，优先建议补充核验材料。
5. 只输出 JSON，不要 Markdown。

JSON 格式：
{{
  "priority": "low|medium|high|urgent",
  "recommended_actions": [],
  "monitoring_items": [],
  "verification_needed": [],
  "do_not_do": []
}}

上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()


def _fallback_impact(context: dict[str, object], reason: str) -> dict[str, object]:
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    assets = []
    platforms = []
    if isinstance(entities, dict):
        assets = list(entities.get("coins") or entities.get("tokens") or [])[:6]
        platforms = list(entities.get("exchanges") or [])[:6]
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    return {
        "affected_assets": assets,
        "affected_platforms": platforms,
        "affected_users": ["相关资产持有者", "相关平台用户"] if score > 20 else [],
        "impact_channels": ["市场情绪", "流动性变化"] if score > 20 else ["持续监测"],
        "impact_summary": _compact("LLM 不可用，基于实体和分数生成保守影响对象。"),
        "uncertainty": [reason],
        "source": "fallback",
    }


def _fallback_advice(context: dict[str, object], reason: str) -> dict[str, object]:
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    priority = "urgent" if score >= 76 else "high" if score >= 61 else "medium" if score >= 41 else "low"
    return {
        "priority": priority,
        "recommended_actions": [
            "核验官方公告和链上证据",
            "降低未核实事件的操作暴露",
            "跟踪事件后续处置进展",
        ],
        "monitoring_items": ["官方公告", "链上资金流向", "交易所状态页"],
        "verification_needed": ["事件时间线", "影响范围", "是否已有缓解措施"],
        "do_not_do": ["不要基于单条消息做交易决策"],
        "source": "fallback",
        "reason": reason,
    }


def analyze_impact_objects(context: dict[str, object]) -> dict[str, object]:
    result = call_llm_json(_impact_prompt(context), temperature=0.0)
    if result.get("_llm_error"):
        return _fallback_impact(context, str(result["_llm_error"]))
    return {
        "affected_assets": list(result.get("affected_assets") or [])[:8],
        "affected_platforms": list(result.get("affected_platforms") or [])[:8],
        "affected_users": list(result.get("affected_users") or [])[:8],
        "impact_channels": list(result.get("impact_channels") or [])[:8],
        "impact_summary": _compact(result.get("impact_summary")),
        "uncertainty": list(result.get("uncertainty") or [])[:6],
        "source": "llm",
    }


def generate_risk_advice(context: dict[str, object]) -> dict[str, object]:
    result = call_llm_json(_advice_prompt(context), temperature=0.0)
    if result.get("_llm_error"):
        return _fallback_advice(context, str(result["_llm_error"]))
    priority = str(result.get("priority") or "medium")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"
    return {
        "priority": priority,
        "recommended_actions": [_compact(item, 45) for item in list(result.get("recommended_actions") or [])[:6]],
        "monitoring_items": [_compact(item, 45) for item in list(result.get("monitoring_items") or [])[:6]],
        "verification_needed": [_compact(item, 45) for item in list(result.get("verification_needed") or [])[:6]],
        "do_not_do": [_compact(item, 45) for item in list(result.get("do_not_do") or [])[:4]],
        "source": "llm",
    }


def run_final_context_agents(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    decision: DecisionResult,
) -> dict[str, object]:
    context = _build_context(case_input, signal_scan, decision)
    with ThreadPoolExecutor(max_workers=2) as executor:
        impact_future = executor.submit(analyze_impact_objects, context)
        advice_future = executor.submit(generate_risk_advice, context)
        impact = impact_future.result()
        advice = advice_future.result()
    return {
        "impact_analysis": impact,
        "advice_generation": advice,
        "context_keys": list(context.keys()),
    }
