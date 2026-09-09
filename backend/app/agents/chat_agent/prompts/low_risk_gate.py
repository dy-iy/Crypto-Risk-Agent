from __future__ import annotations

import json

from app.agents.chat_agent.schemas import RiskCaseInput, SignalScanResult
from app.agents.chat_agent.tools.risk_scanner import DIRECT_HIGH_RISK_TYPES, RISK_NAME_MAP, THRESHOLD_HIGH_RISK_TYPES


def build_low_risk_gate_prompt(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    current_route: str = "low_risk_path",
) -> str:
    risk_type_stats = signal_scan.debug.get("risk_type_stats", [])
    high_risk_route = signal_scan.debug.get("high_risk_route", {})
    payload = {
        "text": case_input.content or case_input.raw_text,
        "input_type": case_input.input_type,
        "entities": case_input.entities,
        "current_route": current_route,
        "current_risk_score": max(
            (int(round(float(score) * 100)) for score in signal_scan.raw_rule_scores.values()),
            default=0,
        ),
        "route_rule": {
            "direct_high_risk": sorted(DIRECT_HIGH_RISK_TYPES),
            "threshold_high_risk": sorted(THRESHOLD_HIGH_RISK_TYPES),
            "threshold_condition": "score > 40 才进入高风险 path",
        },
        "risk_type_stats": risk_type_stats,
        "raw_rule_scores": signal_scan.raw_rule_scores,
        "high_risk_route": high_risk_route,
    }
    allowed_types = "\n".join(f"- {risk_type}: {risk_name}" for risk_type, risk_name in RISK_NAME_MAP.items())
    compact_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""
你是 CryptoRisk 的风险路由门控 Agent。你的任务是对规则扫描器结果做全量复核：
1. 审核文本是否被错误地放入低风险 path。
2. 对全部 {len(RISK_NAME_MAP)} 类 risk_type 做轻量复核，检查规则是否漏判、误判或分数明显偏差。
3. 本任务采用“新闻风险排行榜评分”口径：攻击、脱锚、坏账是高风险；ETF/投资产品大额净流出、强制平仓、代币解锁冲击、巨鲸集中持仓、监管悬而未决、宏观避险导致资金流出等也应被召回为中风险或高风险。

只允许使用以下 {len(RISK_NAME_MAP)} 类 risk_type：
{allowed_types}

审核要求：
1. 结合原文、当前 risk_type 和 risk_score，判断“继续低风险 path”是否合理。
2. 如果文本明确命中 direct_high_risk 组中的任一风险类型，即使规则分很低，也应输出 escalate_to_high_risk=true。
3. 如果文本命中 threshold_high_risk 组，且你认为真实风险分应大于 40，应输出 escalate_to_high_risk=true。
4. 如果规则漏掉了 risk_type，请在 added_risk_types 中补充，并在 corrected_scores 中给出 0-100 的修正分。
5. 如果规则误命中了 risk_type，请在 suppressed_risk_types 中标记，并在 corrected_scores 中给出较低修正分。
6. confirmed_risk_types 只填写原文证据较明确、值得进入后续分支审核的风险类型。
7. 不要因为普通行情、观点、传闻、无损失维护、内部归集而轻易升级；但出现明确金额、跌幅、净流出、清算、暂停、停止支持、解锁比例、坏账或脱锚时，不应继续输出纯低风险。
8. 评分锚点：普通讨论/上线/交易竞赛/正向流入 <=25；明确风险机制但无实际损失 25-45；实际流出、强平、坏账、连续暴跌、服务停止 50-75；攻击、脱锚、大规模清算、重大坏账 >=80。
9. 类别仲裁：清算/强平优先于巨鲸或攻击误判；跨链桥关闭/停止转账优先于交易所运维；市场暴跌优先于宏观，除非原文明确说明由宏观事件驱动。
10. 必须严格输出 JSON，不要输出 Markdown。

JSON 格式：
{{
  "low_risk_confirmed": true,
  "escalate_to_high_risk": false,
  "confirmed_risk_types": ["score_whale"],
  "reviewed_primary_risk_type": "score_whale",
  "reviewed_risk_score": 35,
  "added_risk_types": [],
  "suppressed_risk_types": [],
  "corrected_scores": {{}},
  "reason": "一句话说明审核理由"
}}

待审核输入：
{compact_payload}
""".strip()
